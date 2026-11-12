"""Portable regression cases for frozen sample-distribution arithmetic."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_quantitative as validator


def fixture():
    analysis = {'evidence': [
        {'id': 'e1', 'platform': 'test', 'note_id': 'post1', 'unit_id': 'c1'},
        {'id': 'e2', 'platform': 'test', 'note_id': 'post1', 'unit_id': 'c2'},
        {'id': 'e3', 'platform': 'test', 'note_id': 'post2', 'unit_id': 'c3'},
    ], 'annotations': [{'evidence_id': 'e1', 'status': 'admitted'},
                       {'evidence_id': 'e2', 'status': 'admitted'},
                       {'evidence_id': 'e3', 'status': 'excluded'}]}
    opinions = {'meta': {}, 'opinions': [{'id': 'o1', 'evidence_id': 'e1'}, {'id': 'o2', 'evidence_id': 'e2'}]}
    plan = {'schema_version': 'quantitative-spec-v1', 'mode': 'sample_distribution',
            'questions': [{'id': 'Q1'}],
            'required_tables': [{'id': 'table1', 'axis_id': 'axis1', 'question_ids': ['Q1']}]}
    coding = {'schema_version': 'quantitative-coding-v1', 'axes': [
        {'id': 'axis1', 'title': 'Theme coverage', 'unit': 'source', 'multi_label': True,
         'scope_ids': ['e1', 'e2'], 'categories': [{'id': 'topic', 'label': 'Topic'}, {'id': 'unknown', 'label': 'Unknown'}],
         'unknown_category_id': 'unknown', 'eligibility': 'Relevant admitted test sources', 'window': 'fixture'}],
        'assignments': [{'axis_id': 'axis1', 'entity_id': 'e1', 'category_ids': ['topic']},
                        {'axis_id': 'axis1', 'entity_id': 'e2', 'category_ids': ['unknown']}]}
    facts = {'schema_version': 'quantitative-facts-v1', 'tables': [
        {'id': 'table1', 'axis_id': 'axis1', 'unit': 'source', 'multi_label': True, 'rows': [
            {'category_id': 'topic', 'label': 'Topic', 'numerator_ids': ['e1'], 'denominator_ids': ['e1', 'e2'], 'n': 1, 'N': 2, 'percent': 50.0, 'discussion_pages': 1},
            {'category_id': 'unknown', 'label': 'Unknown', 'numerator_ids': ['e2'], 'denominator_ids': ['e1', 'e2'], 'n': 1, 'N': 2, 'percent': 50.0, 'discussion_pages': 1}]}]}
    return dict(analysis=analysis, opinions=opinions, plan=plan, coding=coding, facts=facts)


class QuantitativeRegression(unittest.TestCase):
    def check_case(self, mutate, expected):
        data = fixture()
        mutate(data)
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            def save(name, value):
                path = run / name
                path.write_text(json.dumps(value, indent=2), encoding="utf-8")
                return hashlib.sha256(path.read_bytes()).hexdigest()
            ah = save("analysis.json", data["analysis"])
            data["opinions"]["meta"]["source_sha256"] = ah
            oh = save("opinions.json", data["opinions"])
            data["coding"].update(source_analysis_sha256=ah, source_opinions_sha256=oh)
            ch = save("quantitative-coding.json", data["coding"])
            data["facts"]["source_coding_sha256"] = ch
            save("quantitative-facts.json", data["facts"])
            save("quantitative-spec.json", data["plan"])
            result = validator.validate(run)
            self.assertIs(result["ok"], expected, result)

    def test_valid(self):
        self.check_case(lambda d: None, True)

    def test_missing_required_table(self):
        self.check_case(lambda d: d["facts"].update(tables=[]), False)

    def test_missing_assignment(self):
        self.check_case(lambda d: d["coding"]["assignments"].pop(), False)

    def test_fabricated_numerator(self):
        self.check_case(lambda d: d["facts"]["tables"][0]["rows"][0].update(numerator_ids=["e1", "e2"]), False)

    def test_tampered_percent(self):
        self.check_case(lambda d: d["facts"]["tables"][0]["rows"][0].update(percent=99.0), False)

    def test_exclusive_overlap(self):
        def change(d):
            d["coding"]["axes"][0].update(multi_label=False, unknown_category_id=None)
            d["facts"]["tables"][0]["multi_label"] = False
            d["coding"]["assignments"][0]["category_ids"] = ["topic", "unknown"]
        self.check_case(change, False)

    def test_excluded_denominator(self):
        def change(d):
            d["coding"]["axes"][0]["scope_ids"].append("e3")
            d["coding"]["assignments"].append({"axis_id":"axis1", "entity_id":"e3", "category_ids":["topic"]})
        self.check_case(change, False)

    def empty(self, d):
        d["coding"]["axes"][0]["scope_ids"] = []
        d["coding"]["assignments"] = []
        for row in d["facts"]["tables"][0]["rows"]:
            row.update(numerator_ids=[], denominator_ids=[], n=0, N=0, percent=None, discussion_pages=0)

    def test_empty_denominator(self):
        self.check_case(self.empty, True)

    def test_empty_denominator_cannot_show_zero_percent(self):
        def change(d):
            self.empty(d)
            d["facts"]["tables"][0]["rows"][0]["percent"] = 0.0
        self.check_case(change, False)

    def test_unknown_overlap(self):
        self.check_case(lambda d: d["coding"]["assignments"][0].update(category_ids=["topic", "unknown"]), False)

    def test_duplicate_source_identity(self):
        self.check_case(lambda d: d["analysis"]["evidence"][1].update(unit_id="c1"), False)

    def test_case_exploration(self):
        self.check_case(lambda d: d["plan"].update(mode="case_exploration", required_tables=[]), True)


if __name__ == "__main__":
    unittest.main()
