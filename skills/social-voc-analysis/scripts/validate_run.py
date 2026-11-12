"""Validate one local research run against its plan; never create completion claims.

Profiles: analysis inspects research progress; delivery/revision also require
documented report review and frozen output bindings. All checks are offline.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path

import research_plan
import validate_analysis
import validate_coverage
import validate_opinions
import validate_quantitative
import validate_research_modules


def validate(run_dir, profile="analysis"):
    run = Path(run_dir).resolve()
    errors, warnings, checks = [], [], {}
    dimensions = {key: {"status": "not_run"} for key in (
        "research_plan", "data_integrity", "processing_coverage", "review_coverage",
        "question_coverage", "quantitative", "modules", "artifact_dependencies",
        "report_binding", "report_review")}
    result = {"schema_version": "run-validation-v1", "profile": profile,
              "status": "in_progress", "ok": False, "errors": errors,
              "warnings": warnings, "checks": checks, "dimensions": dimensions,
              "semantic_accuracy_verified": False, "sampling_representativeness_verified": False}
    if profile not in {"analysis", "delivery", "revision"}:
        errors.append("unknown validation profile")
        result["status"] = "invalid"
        return result
    final = profile != "analysis"

    def read(name):
        value = json.loads(research_plan.local_path(run, name).read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError(name + " must be an object")
        return value

    def record(name, checked):
        checks[name] = checked
        for x in checked.get("errors", []):
            errors.append({"check": name, "detail": x})
        for x in checked.get("warnings", []):
            warnings.append({"check": name, "detail": x})
        return not checked.get("errors")

    def invoke(name, action):
        try:
            checked = action()
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError) as exc:
            checked = {"errors": [f"{type(exc).__name__}: {exc}"], "warnings": []}
        return record(name, checked)

    planned = research_plan.validate(run / "research-spec.json", strict=final)
    plan = planned["plan"]
    record("research_plan", {k: v for k, v in planned.items() if k != "plan"})
    dimensions["research_plan"]["status"] = "passed" if planned["ok"] else "failed"
    modern = plan.get("schema_version") == "research-spec-v1"
    if not planned["ok"]:
        result["status"] = "invalid"
        return result
    analysis_name = "analysis.json"
    try:
        if not (run / analysis_name).is_file() and not modern and not final:
            explicit = []
            old_input = plan.get("input")
            if isinstance(old_input, dict) and research_plan.text(old_input.get("source_analysis")):
                explicit.append(old_input["source_analysis"])
            if (run / "opinions.json").is_file():
                old_meta = read("opinions.json").get("meta")
                if isinstance(old_meta, dict) and research_plan.text(old_meta.get("source_analysis")):
                    explicit.append(old_meta["source_analysis"])
            targets = {research_plan.local_path(run, name) for name in explicit}
            if len(targets) > 1:
                raise ValueError("historical plan and opinion layer name conflicting source snapshots")
            if targets:
                analysis_name = next(iter(targets)).relative_to(run).as_posix()
                warnings.append("Inspecting explicitly named historical source " + analysis_name + "; canonical run coverage remains unverified.")
        analysis = read(analysis_name)
    except (OSError, ValueError, TypeError) as exc:
        errors.append(str(exc))
        result["status"] = "invalid"
        return result
    try:
        ae, aw, summary = validate_analysis.validate(analysis, research_plan.local_path(run, analysis_name).parent)
        integrity = record("analysis", {"errors": ae, "warnings": aw, "summary": summary})
    except (TypeError, KeyError, AttributeError, ValueError) as exc:
        integrity = record("analysis", {"errors": [str(exc)]})
        summary = {}
    dimensions["data_integrity"]["status"] = "passed" if integrity else "failed"
    opinions = None
    if (run / "opinions.json").exists():
        if invoke("opinions", lambda: validate_opinions.validate(run / "opinions.json")):
            opinions = read("opinions.json")
        else:
            dimensions["data_integrity"]["status"] = "failed"
    if (run / "items.jsonl").exists() and analysis_name == "analysis.json":
        invoke("coverage", lambda: validate_coverage.validate(run))
        coverage = checks["coverage"]
        counts = coverage.get("summary", {})
        processing_complete = bool(coverage.get("structurally_accounted") and counts.get("normalized_source_units", 0) > 0
                                   and counts.get("full_input_text_represented_units") == counts.get("normalized_source_units"))
        dimensions["processing_coverage"]["status"] = "passed" if processing_complete else "incomplete"
        dimensions["review_coverage"]["status"] = "passed" if coverage.get("review_records_complete") else "incomplete"
    else:
        warnings.append("No canonical analysis/items pair; normalized-input and full-text review coverage were not verified.")
        coverage = {}
        processing_complete = False
        if final:
            errors.append("delivery/revision requires items.jsonl and documented review coverage")
    states = summary.get("states", {})
    pending = states.get("pending", 0)
    uncertain_ids = set(coverage.get("summary", {}).get("uncertain_segment_source_ids", []))
    uncertain_ids.update(row["evidence_id"] for row in analysis.get("annotations", [])
                         if isinstance(row, dict) and row.get("status") == "uncertain" and isinstance(row.get("evidence_id"), str))
    uncertain = len(uncertain_ids)
    result["unresolved"] = {"pending_sources": pending, "uncertain_sources": uncertain}
    if final and (pending or not coverage.get("review_records_complete") or not processing_complete):
        errors.append("delivery/revision requires complete processing and documented full-text review; uncertain may remain disclosed")

    selected = set()
    for row in plan.get("module_plan", []):
        if row.get("selected"):
            selected.add(row["module"])
            for filename in row.get("required_artifacts", []):
                if not research_plan.local_path(run, filename).is_file():
                    errors.append("selected module missing required artifact: " + filename)
    if selected & {"opinions", "opinion", "观点与聚类"} and not (run / "opinions.json").is_file():
        errors.append("selected opinion module requires opinions.json")
    requested = []
    for module, filename, aliases in (
        ("keywords", "keyword-coding.json", {"keywords", "keyword", "词语与词云", "关键词"}),
        ("journey", "journey-map.json", {"journey", "场景与旅程", "旅程"}),
    ):
        enabled = bool(selected & aliases) or plan.get(module.rstrip("s") + "_plan", {}).get("enabled") is True
        if enabled or (run / filename).exists():
            requested.append(module)
            invoke(module, lambda m=module: validate_research_modules.validate(run, m))
    dimensions["modules"]["status"] = ("failed" if any(checks[m].get("errors") for m in requested) else "passed") if requested else "not_applicable"
    quant = plan.get("quantitative_plan", {})
    if quant.get("mode") == "sample_distribution" or quant.get("required_tables") or (run / "quantitative-spec.json").exists():
        passed = invoke("quantitative", lambda: validate_quantitative.validate(run))
        dimensions["quantitative"]["status"] = "passed" if passed else "failed"
    else:
        dimensions["quantitative"]["status"] = "not_applicable"

    findings = {}
    for doc in (analysis, opinions or {}):
        for row in doc.get("findings", []):
            if isinstance(row, dict) and research_plan.text(row.get("id")):
                findings[row["id"]] = row
    question_ids = {row["id"] for row in plan["question_plan"]}
    for fid, finding in findings.items():
        refs = finding.get("question_ids", finding.get("research_question_ids"))
        if modern and refs is None:
            errors.append(fid + " must link explicit research question IDs")
        if refs is not None and (not isinstance(refs, list) or any(not isinstance(x, str) for x in refs) or not set(refs) <= question_ids):
            errors.append(fid + " references unknown research questions")
    table_ids = set()
    table_questions = {}
    if (run / "quantitative-facts.json").exists():
        table_ids = {r.get("id") for r in read("quantitative-facts.json").get("tables", []) if isinstance(r, dict) and isinstance(r.get("id"), str)}
    if (run / "quantitative-spec.json").exists():
        table_questions = {row["id"]: row.get("question_ids", []) for row in read("quantitative-spec.json").get("required_tables", [])
                           if isinstance(row, dict) and isinstance(row.get("id"), str)}
    answered, question_unknown = set(), False
    for row in plan.get("question_coverage", []):
        qid = row["question_id"]
        answered.add(qid)
        fids, tids = row.get("finding_ids", []), row.get("table_ids", [])
        if set(fids) - set(findings) or set(tids) - table_ids:
            errors.append(qid + " answer references missing finding/table")
        for fid in set(fids) & set(findings):
            linked = findings[fid].get("question_ids", findings[fid].get("research_question_ids", []))
            if not isinstance(linked, list) or qid not in linked:
                errors.append(qid + " uses a finding linked to a different question: " + fid)
        for tid in set(tids) & table_ids:
            if qid not in table_questions.get(tid, []):
                errors.append(qid + " uses a table linked to a different question: " + tid)
        if row["status"] == "answered" and not (fids or tids):
            errors.append(qid + " answered question needs a linked finding or table")
        if row["status"] != "answered":
            question_unknown = True
    complete_questions = answered == question_ids
    dimensions["question_coverage"]["status"] = "passed" if complete_questions else "incomplete"
    if not complete_questions:
        warnings.append("Question answer matrix is incomplete; research completion is not established.")

    outputs = [x for x in plan.get("outputs", []) if isinstance(x, dict)]
    if final:
        if not outputs:
            errors.append("delivery/revision requires explicit outputs")
        for output in outputs:
            if not research_plan.local_path(run, output["path"]).is_file():
                errors.append("planned output missing: " + output["path"])
    for name, filename, module in (
        ("artifact_dependencies", "artifact-manifest.json", "artifact_manifest"),
        ("report_binding", "report-bindings.json", "validate_report_bindings"),
    ):
        required = final and modern and (name == "artifact_dependencies" or any(x.get("format", "").lower() == "html" for x in outputs))
        if required or (run / filename).exists():
            passed = invoke(name, lambda m=module: importlib.import_module(m).validate(run))
            if passed and name == "artifact_dependencies" and final:
                manifest = read(filename)
                covered = {row.get("path") for row in manifest.get("artifacts", []) if isinstance(row, dict) and isinstance(row.get("path"), str)}
                expected = {"research-spec.json", "analysis.json", "items.jsonl", "review-ledger.json", "quality-review.json"}
                expected.update(x["path"] for x in outputs)
                for filename in ("opinions.json", "quantitative-spec.json", "quantitative-coding.json", "quantitative-facts.json", "keyword-coding.json", "journey-map.json", "report-bindings.json"):
                    if (run / filename).is_file():
                        expected.add(filename)
                missing = expected - covered
                if missing:
                    message = "artifact manifest omits delivery inputs/outputs: " + ", ".join(sorted(missing))
                    errors.append(message)
                    checks[name].setdefault("errors", []).append(message)
                    checks[name]["ok"] = False
                    passed = False
            dimensions[name]["status"] = "passed" if passed else "failed"
        else:
            dimensions[name]["status"] = "not_applicable" if final else "not_run"
    if final:
        invoke("report_review", lambda: validate_review(run, outputs))
        dimensions["report_review"]["status"] = "passed" if not checks["report_review"].get("errors") else "failed"
    complete = bool(coverage.get("review_records_complete") and processing_complete and not pending and complete_questions)
    result["ok"] = not errors
    if errors:
        result["status"] = "invalid"
    elif complete and (modern or final):
        result["status"] = "completed_with_uncertainty" if uncertain or question_unknown else "ready"
    else:
        result["status"] = "in_progress"
    if not modern:
        warnings.append("Historical inspection does not establish current-plan delivery readiness.")
    if opinions and opinions.get("findings") and not checks["opinions"].get("errors"):
        old = "No findings recorded; this snapshot is not a completed analytical report."
        replacement = "Source layer has no findings; validated independent opinion findings are used."
        for row in warnings:
            if isinstance(row, dict) and isinstance(row.get("detail"), str):
                row["detail"] = row["detail"].replace(old, replacement)
        for check in checks.values():
            if isinstance(check.get("warnings"), list):
                check["warnings"] = [x.replace(old, replacement) if isinstance(x, str) else x for x in check["warnings"]]
    return result


def validate_review(run, outputs):
    errors = []
    path = run / "quality-review.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(doc, dict) or doc.get("schema_version") != "quality-review-v1":
            raise ValueError("quality-review-v1 record required")
        dimensions = doc.get("dimensions")
        if not isinstance(dimensions, dict):
            raise ValueError("quality-review.dimensions must be an object")
        visual_required = any(x.get("format", "").lower() in {"html", "pdf"} for x in outputs)
        for key in ("data_evidence", "language", "hierarchy", "visual_interaction"):
            row = dimensions.get(key)
            if not isinstance(row, dict) or row.get("status") not in {"passed", "not_run", "not_applicable"} or not research_plan.text(row.get("method")):
                errors.append("quality-review missing explicit status/method: " + key)
                continue
            required = key != "visual_interaction" or visual_required
            if required and row["status"] != "passed":
                errors.append("quality-review not completed: " + key)
            if row["status"] == "not_applicable" and not research_plan.text(row.get("reason")):
                errors.append("quality-review not_applicable needs reason: " + key)
        hashes = doc.get("source_hashes")
        if not isinstance(hashes, dict) or not hashes:
            raise ValueError("quality-review.source_hashes must bind reviewed files")
        required_paths = {"research-spec.json", "analysis.json"} | {x["path"] for x in outputs}
        for filename in ("items.jsonl", "review-ledger.json", "opinions.json", "quantitative-spec.json", "quantitative-coding.json",
                         "quantitative-facts.json", "keyword-coding.json", "journey-map.json", "report-bindings.json"):
            if (run / filename).is_file():
                required_paths.add(filename)
        if not required_paths <= set(hashes):
            errors.append("quality-review does not bind current plan, analysis and every output")
        for filename, expected in hashes.items():
            actual = hashlib.sha256(research_plan.local_path(run, filename).read_bytes()).hexdigest()
            if actual != expected:
                errors.append("stale quality review: " + filename)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    return {"ok": not errors, "errors": errors, "warnings": [],
            "limits": ["Review records document stated work; this script cannot establish semantic or visual quality."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--profile", choices=["analysis", "delivery", "revision"], default="analysis")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.run_dir, args.profile)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = {"ok": False, "status": "invalid", "errors": [str(exc)], "warnings": []}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["ok"] and (args.profile == "analysis" or result["status"] in {"ready", "completed_with_uncertainty"}) else 1


if __name__ == "__main__":
    raise SystemExit(main())
