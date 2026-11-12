"""Offline cross-layer regressions, with generated fixtures and no project dependencies."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import research_plan
import validate_opinions
import validate_quantitative
import validate_run
import artifact_manifest


def write(run, name, value):
    path = run / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review_hashes(run, output):
    files = ["research-spec.json", "analysis.json", output, "items.jsonl", "review-ledger.json", "opinions.json",
             "quantitative-spec.json", "quantitative-coding.json", "quantitative-facts.json", "keyword-coding.json", "journey-map.json", "report-bindings.json"]
    return {name: sha(run / name) for name in files if (run / name).is_file()}


def fixture(run, state="admitted", ledger=True):
    text = "I use product A."
    write(run, "raw/source.json", {"text": text})
    evidence = {"id": "E1", "platform": "xiaohongshu", "note_id": "N1", "unit_id": "body",
                "unit_type": "note", "text_kind": "full_text", "text": text,
                "published_at": "2026-11-09", "collected_at": "2026-11-09T12:00:00+08:00",
                "url": "https://example.invalid/n1", "raw_ref": {"file": "raw/source.json", "pointer": "/text"}}
    finding = {"id": "F1", "claim": "One source describes use", "interpretation": "Use is stated",
               "limits": "Only one source", "opportunity": "Not a design task", "validation": "Return to source",
               "support_ids": ["E1"], "counter_ids": [], "research_question_ids": ["Q1"]}
    analysis = {"meta": {"run_id": "fixture", "collection_mode": "offline", "coding_version": "v1",
                         "stage": "final", "analysis_as_of": "2026-11-10T12:00:00+08:00"},
                "coding_rules": {"version": "v1", "themes": [{"id": "T1", "definition": "Use", "include": ["Stated use"], "exclude": []}]},
                "evidence": [evidence], "annotations": [{"evidence_id": "E1", "status": state, "reason": "Stated use" if state == "admitted" else "Needs context",
                                                         "assessor": "model", "coding_version": "v1", "primary_theme": "T1"}],
                "findings": [finding] if state == "admitted" else []}
    write(run, "analysis.json", analysis)
    items = {"platform": "xiaohongshu", "content_id": "N1", "unit_id": "body", "text": text}
    (run / "items.jsonl").write_text(json.dumps(items) + "\n", encoding="utf-8")
    plan = {"schema_version": "research-spec-v1", "collection_mode": "offline",
            "external_access": {"provider": "guaikei", "transport": "mcp"},
            "question_plan": [{"id": "Q1", "question": "Does this source describe use?", "evidence_needed": "Original use statement",
                               "method": "Read the full text", "completion_criteria": "Answer or record missing context"}],
            "module_plan": [], "quantitative_plan": {"mode": "case_exploration", "required_tables": []},
            "outputs": [], "question_coverage": [{"question_id": "Q1", "status": "answered" if state == "admitted" else "unknown",
                                                  "finding_ids": ["F1"] if state == "admitted" else [], "table_ids": [],
                                                  "gaps": [] if state == "admitted" else ["Object needs context"]}]}
    write(run, "research-spec.json", plan)
    if ledger:
        write(run, "review-ledger.json", {"schema_version": "coverage-review-v1", "source_items_sha256": sha(run / "items.jsonl"),
              "source_analysis_sha256": sha(run / "analysis.json"), "source_opinions_sha256": None,
              "review_method": "Read original source and check statement against question",
              "reviews": [{"evidence_id": "E1", "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                           "assessor": "model", "review_status": "pending" if state == "pending" else "complete",
                           "segments": [{"start": 0, "end": len(text), "outcome": "uncertain" if state == "uncertain" else "background",
                                         "opinion_ids": [], "reason": "Use fact without evaluation" if state == "admitted" else "Missing object context"}]}]})
    return plan, analysis


def opinion_fixture(run):
    fixture(run)
    opinion = {"id": "O1", "evidence_id": "E1", "source_key": "E1", "product": "A", "aspect": "usage",
               "polarity": "neutral", "kind": "self_report", "evidence_role": "experience", "statement": "Describes use",
               "quote": "I use product A.", "candidate_theme": "T1", "scene": None, "journey_stage": None,
               "behavior": None, "expectation": None, "consequence": None, "limits": None}
    doc = {"meta": {"schema_version": "opinions-v1", "source_analysis": "analysis.json", "source_sha256": sha(run / "analysis.json"),
                    "coding_version": "v1", "analysis_as_of": "2026-11-10T12:00:00+08:00", "review_complete": True},
           "source_reviews": [{"evidence_id": "E1", "source_key": "E1", "status": "admitted", "reason": "Explicit use", "opinion_ids": ["O1"]}],
           "opinions": [opinion], "clusters": [{"id": "T1", "title": "Use", "definition": "Stated use", "opinion_ids": ["O1"]}],
           "findings": [{"id": "OF1", "claim": "Use is stated", "interpretation": "One source", "limits": "One source",
                         "support_opinion_ids": ["O1"], "counter_opinion_ids": [], "question_ids": ["Q1"]}]}
    write(run, "opinions.json", doc)
    return doc


class RunValidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.run = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_normalizes_without_mutating_input(self):
        old = {"questions": [{"id": "Q1", "question": "Why?", "evidence": "Text", "analysis_method": "Read", "completion_criterion": "Answer"}]}
        original = copy.deepcopy(old)
        checked = research_plan.validate(old)
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["plan"]["question_plan"][0]["method"], "Read")
        self.assertEqual(old, original)
        self.assertFalse(research_plan.validate(old, strict=True)["ok"])

    def test_new_plan_rejects_other_external_provider(self):
        plan, _ = fixture(self.run)
        plan["external_access"] = {"provider": "another-service", "transport": "http"}
        self.assertFalse(research_plan.validate(plan)["ok"])

    def test_malformed_module_and_quantitative_shapes_are_rejected(self):
        plan, _ = fixture(self.run)
        plan["module_plan"] = [{"module": "journey", "selected": True, "question_ids": ["Q1"], "required_artifacts": None}]
        self.assertFalse(research_plan.validate(plan)["ok"])
        self.assertTrue(research_plan.check_quantitative_plan(plan, {"questions": None, "required_tables": []}))
        self.assertTrue(research_plan.check_quantitative_plan(plan, []))
        plan["module_plan"] = []
        plan["quantitative_plan"]["mode"] = None
        self.assertFalse(research_plan.validate(plan)["ok"])

    def test_unknown_opinion_question_is_rejected(self):
        doc = opinion_fixture(self.run)
        self.assertEqual(validate_opinions.validate(self.run / "opinions.json")["errors"], [])
        doc["findings"][0]["question_ids"] = ["UNDECLARED"]
        write(self.run, "opinions.json", doc)
        self.assertTrue(any("absent from research-spec" in e for e in validate_opinions.validate(self.run / "opinions.json")["errors"]))

    def test_missing_plan_keeps_legacy_opinions_inspectable(self):
        opinion_fixture(self.run)
        (self.run / "research-spec.json").unlink()
        checked = validate_opinions.validate(self.run / "opinions.json")
        self.assertEqual(checked["errors"], [])
        self.assertTrue(checked["warnings"])

    def test_explicit_historical_source_alias_is_inspected_without_copying(self):
        opinion = opinion_fixture(self.run)
        (self.run / "source-analysis.json").write_bytes((self.run / "analysis.json").read_bytes())
        (self.run / "analysis.json").unlink()
        opinion["meta"]["source_analysis"] = "source-analysis.json"
        write(self.run, "opinions.json", opinion)
        plan = json.loads((self.run / "research-spec.json").read_text(encoding="utf-8"))
        plan.pop("schema_version")
        plan["input"] = {"source_analysis": "source-analysis.json"}
        write(self.run, "research-spec.json", plan)
        checked = validate_run.validate(self.run)
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["status"], "in_progress")
        self.assertFalse((self.run / "analysis.json").exists())
        self.assertFalse(validate_run.validate(self.run, "delivery")["ok"])

    def test_independent_findings_do_not_require_duplicate_source_findings(self):
        doc = opinion_fixture(self.run)
        analysis = json.loads((self.run / "analysis.json").read_text(encoding="utf-8"))
        analysis["findings"] = []
        write(self.run, "analysis.json", analysis)
        doc["meta"]["source_sha256"] = sha(self.run / "analysis.json")
        write(self.run, "opinions.json", doc)
        (self.run / "review-ledger.json").unlink()
        plan = json.loads((self.run / "research-spec.json").read_text(encoding="utf-8"))
        plan["question_coverage"][0]["finding_ids"] = ["OF1"]
        write(self.run, "research-spec.json", plan)
        checked = validate_run.validate(self.run)
        self.assertTrue(checked["ok"], checked)
        self.assertFalse(any("not a completed analytical report" in str(row) for row in checked["warnings"]))

    def test_quantitative_obligation_drift_is_rejected(self):
        plan, _ = fixture(self.run)
        plan["quantitative_plan"] = {"mode": "sample_distribution", "required_tables": [{"id": "T-use", "axis_id": "A-use", "question_ids": ["Q1"]}]}
        bad = {"mode": "sample_distribution", "questions": [{"id": "Q1"}], "required_tables": []}
        self.assertTrue(research_plan.check_quantitative_plan(plan, bad))
        bad["required_tables"] = [{"id": "T-use", "axis_id": "OTHER", "question_ids": ["Q1"]}]
        self.assertTrue(research_plan.check_quantitative_plan(plan, bad))

    def test_case_spec_cannot_hide_planned_distribution(self):
        plan, _ = fixture(self.run)
        plan["quantitative_plan"] = {"mode": "sample_distribution", "required_tables": [{"id": "T-use", "axis_id": "A-use", "question_ids": ["Q1"]}]}
        write(self.run, "research-spec.json", plan)
        write(self.run, "quantitative-spec.json", {"schema_version": "quantitative-spec-v1", "mode": "case_exploration", "questions": [{"id": "Q1"}], "required_tables": []})
        checked = validate_quantitative.validate(self.run)
        self.assertTrue(any("mode differs" in e for e in checked["errors"]))

    def test_selected_module_missing_is_error(self):
        plan, _ = fixture(self.run)
        plan["module_plan"] = [{"module": "journey", "selected": True, "question_ids": ["Q1"]}]
        write(self.run, "research-spec.json", plan)
        checked = validate_run.validate(self.run)
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["dimensions"]["modules"]["status"], "failed")

    def test_complete_review_can_preserve_real_uncertainty(self):
        fixture(self.run, state="uncertain")
        checked = validate_run.validate(self.run)
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["status"], "completed_with_uncertainty")
        self.assertEqual(checked["dimensions"]["review_coverage"]["status"], "passed")
        self.assertEqual(checked["unresolved"]["pending_sources"], 0)

    def test_uncertain_annotations_and_segments_count_distinct_source_union(self):
        _, analysis = fixture(self.run, state="uncertain")
        other = dict(analysis["evidence"][0], id="E2", note_id="N2", text="Another source.", raw_ref={"file": "raw/source2.json", "pointer": "/text"})
        write(self.run, "raw/source2.json", {"text": other["text"]})
        analysis["evidence"].append(other)
        analysis["annotations"].append({"evidence_id": "E2", "status": "admitted", "reason": "Relevant statement", "assessor": "model", "coding_version": "v1", "primary_theme": "T1"})
        write(self.run, "analysis.json", analysis)
        with (self.run / "items.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"platform": "xiaohongshu", "content_id": "N2", "unit_id": "body", "text": other["text"]}) + "\n")
        ledger = json.loads((self.run / "review-ledger.json").read_text(encoding="utf-8"))
        ledger["source_analysis_sha256"], ledger["source_items_sha256"] = sha(self.run / "analysis.json"), sha(self.run / "items.jsonl")
        ledger["reviews"][0]["segments"][0]["outcome"] = "background"
        ledger["reviews"].append({"evidence_id": "E2", "text_sha256": hashlib.sha256(other["text"].encode()).hexdigest(), "assessor": "model", "review_status": "complete",
                                  "segments": [{"start": 0, "end": len(other["text"]), "outcome": "uncertain", "opinion_ids": [], "reason": "Meaning needs context"}]})
        write(self.run, "review-ledger.json", ledger)
        checked = validate_run.validate(self.run)
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["unresolved"]["uncertain_sources"], 2)

    def test_missing_review_ledger_cannot_be_ready(self):
        fixture(self.run, ledger=False)
        checked = validate_run.validate(self.run)
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["status"], "in_progress")
        self.assertEqual(checked["dimensions"]["review_coverage"]["status"], "incomplete")

    def test_pending_is_not_uncertainty_completion(self):
        fixture(self.run, state="pending")
        checked = validate_run.validate(self.run)
        self.assertEqual(checked["status"], "in_progress", checked)
        self.assertEqual(checked["unresolved"]["pending_sources"], 1)

    def test_unknown_answer_requires_gap_and_answered_requires_evidence(self):
        plan, _ = fixture(self.run)
        plan["question_coverage"][0].update(status="unknown", gaps=[])
        self.assertFalse(research_plan.validate(plan)["ok"])
        plan["question_coverage"][0].update(status="answered", finding_ids=[])
        write(self.run, "research-spec.json", plan)
        self.assertFalse(validate_run.validate(self.run)["ok"])

    def test_answer_cannot_borrow_finding_from_another_question(self):
        plan, _ = fixture(self.run)
        plan["question_plan"].append(dict(plan["question_plan"][0], id="Q2", question="Another question"))
        plan["question_coverage"].append({"question_id": "Q2", "status": "answered", "finding_ids": ["F1"], "table_ids": []})
        write(self.run, "research-spec.json", plan)
        checked = validate_run.validate(self.run)
        self.assertFalse(checked["ok"])
        self.assertTrue(any("different question" in str(x) for x in checked["errors"]))

    def test_full_review_of_short_fragment_cannot_complete_longer_input(self):
        fixture(self.run)
        longer = "I use product A. More context."
        write(self.run, "raw/source.json", {"text": longer})
        (self.run / "items.jsonl").write_text(json.dumps({"platform": "xiaohongshu", "content_id": "N1", "unit_id": "body", "text": longer}) + "\n", encoding="utf-8")
        ledger = json.loads((self.run / "review-ledger.json").read_text(encoding="utf-8"))
        ledger["source_items_sha256"] = sha(self.run / "items.jsonl")
        write(self.run, "review-ledger.json", ledger)
        checked = validate_run.validate(self.run)
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["status"], "in_progress")
        self.assertEqual(checked["dimensions"]["processing_coverage"]["status"], "incomplete")

    def test_review_hash_staleness_is_rejected(self):
        fixture(self.run)
        (self.run / "report.txt").write_text("A finding", encoding="utf-8")
        doc = {"schema_version": "quality-review-v1", "dimensions": {k: {"status": "passed", "method": "Read the actual output"} for k in ("data_evidence", "language", "hierarchy", "visual_interaction")},
               "source_hashes": review_hashes(self.run, "report.txt")}
        write(self.run, "quality-review.json", doc)
        outputs = [{"path": "report.txt", "format": "txt"}]
        self.assertTrue(validate_run.validate_review(self.run, outputs)["ok"])
        (self.run / "report.txt").write_text("Changed finding", encoding="utf-8")
        self.assertFalse(validate_run.validate_review(self.run, outputs)["ok"])

    def test_review_binds_used_statistics_and_rejects_changed_facts(self):
        self.prepare_delivery()
        write(self.run, "quantitative-facts.json", {"tables": [{"id": "T1", "n": 1}]})
        quality = json.loads((self.run / "quality-review.json").read_text(encoding="utf-8"))
        outputs = [{"path": "report.txt", "format": "txt"}]
        self.assertFalse(validate_run.validate_review(self.run, outputs)["ok"])
        quality["source_hashes"] = review_hashes(self.run, "report.txt")
        write(self.run, "quality-review.json", quality)
        self.assertTrue(validate_run.validate_review(self.run, outputs)["ok"])
        write(self.run, "quantitative-facts.json", {"tables": [{"id": "T1", "n": 2}]})
        self.assertFalse(validate_run.validate_review(self.run, outputs)["ok"])

    def test_declared_visual_review_cannot_be_not_run_for_html(self):
        fixture(self.run)
        (self.run / "report.html").write_text("<p>Finding</p>", encoding="utf-8")
        doc = {"schema_version": "quality-review-v1", "dimensions": {k: {"status": "passed", "method": "Read actual output"} for k in ("data_evidence", "language", "hierarchy", "visual_interaction")},
               "source_hashes": review_hashes(self.run, "report.html")}
        doc["dimensions"]["visual_interaction"]["status"] = "not_run"
        write(self.run, "quality-review.json", doc)
        self.assertFalse(validate_run.validate_review(self.run, [{"path": "report.html", "format": "html"}])["ok"])

    def prepare_delivery(self, state="uncertain"):
        plan, _ = fixture(self.run, state=state)
        plan["outputs"] = [{"path": "report.txt", "format": "txt"}]
        write(self.run, "research-spec.json", plan)
        (self.run / "report.txt").write_text("Source needs more object context; no definite use conclusion.", encoding="utf-8")
        quality = {"schema_version": "quality-review-v1", "dimensions": {k: {"status": "passed", "method": "Read the source, frozen result and actual report"} for k in ("data_evidence", "language", "hierarchy")},
                   "source_hashes": review_hashes(self.run, "report.txt")}
        quality["dimensions"]["visual_interaction"] = {"status": "not_applicable", "method": "Plain text deliverable", "reason": "No layout or interaction"}
        write(self.run, "quality-review.json", quality)

    def test_delivery_can_disclose_uncertainty_after_real_checks_are_recorded(self):
        self.prepare_delivery()
        files = ["research-spec.json", "analysis.json", "items.jsonl", "review-ledger.json", "quality-review.json", "report.txt"]
        artifact_manifest.snapshot(self.run, [(str(i), name) for i, name in enumerate(files)])
        checked = validate_run.validate(self.run, "delivery")
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["status"], "completed_with_uncertainty")
        self.assertFalse(checked["semantic_accuracy_verified"])

    def test_manifest_of_unrelated_file_is_not_delivery_coverage(self):
        self.prepare_delivery()
        artifact_manifest.snapshot(self.run, [("report", "report.txt")])
        checked = validate_run.validate(self.run, "delivery")
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["dimensions"]["artifact_dependencies"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
