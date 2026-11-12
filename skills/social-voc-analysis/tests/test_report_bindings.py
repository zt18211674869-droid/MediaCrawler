"""Cross-layer regressions for frozen HTML references and revision tracking."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import artifact_manifest
import validate_report_bindings


class RunFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)

    def write(self, name, value):
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def sha(self, name):
        return hashlib.sha256((self.run / name).read_bytes()).hexdigest()

    def report_fixture(self):
        self.write("facts.json", {"count": 3, "percent": 50.0})
        self.write("analysis.json", {
            "evidence": [{"id": "E1", "text": "这个功能记录很方便，但查找较慢。", "text_kind": "full_text"}],
            "annotations": [{"evidence_id": "E1", "status": "admitted"}],
            "findings": [{"id": "F1", "claim": "记录便利，检索仍有阻力"}]})
        self.html = '<span data-metric-id="M1">3</span><span data-metric-id="M2">50.0%</span><p data-finding-id="F1">记录便利，检索仍有阻力</p><blockquote data-quote-id="Q1">记录很方便</blockquote>'
        (self.run / "report.html").write_text(self.html, encoding="utf-8")
        self.doc = {"schema_version": "report-bindings-v1", "source_hashes": {
            "facts.json": self.sha("facts.json"), "analysis.json": self.sha("analysis.json")},
            "reports": [{"path": "report.html", "metrics": [
                {"id": "M1", "source": {"file": "facts.json", "pointer": "/count"}, "format": "number"},
                {"id": "M2", "source": {"file": "facts.json", "pointer": "/percent"}, "format": "percent", "decimals": 1}],
                "findings": [{"id": "F1", "source": "analysis"}],
                "quotes": [{"id": "Q1", "evidence_id": "E1", "text": "记录很方便"}]}]}
        self.write("report-bindings.json", self.doc)

    def check_report(self):
        return validate_report_bindings.validate(self.run)


class ReportBindingTests(RunFixture):
    def setUp(self):
        super().setUp()
        self.report_fixture()

    def test_frozen_report_passes(self):
        result = self.check_report()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["summary"]["metric_elements"], 2)
        self.assertFalse(result["visual_qa_verified"])

    def test_actual_html_number_is_checked(self):
        (self.run / "report.html").write_text(self.html.replace('>3</span>', ' data-value="3">9</span>'), encoding="utf-8")
        self.assertFalse(self.check_report()["ok"])

    def test_unknown_metric_id_fails(self):
        (self.run / "report.html").write_text(self.html.replace('data-metric-id="M1"', 'data-metric-id="INVENTED"'), encoding="utf-8")
        self.assertFalse(self.check_report()["ok"])

    def test_edited_frozen_facts_fail_hash(self):
        self.write("facts.json", {"count": 9, "percent": 50.0})
        self.assertFalse(self.check_report()["ok"])

    def test_forged_quote_fails_even_if_html_matches(self):
        self.doc["reports"][0]["quotes"][0]["text"] = "用户都很喜欢"
        self.write("report-bindings.json", self.doc)
        (self.run / "report.html").write_text(self.html.replace("记录很方便</blockquote>", "用户都很喜欢</blockquote>"), encoding="utf-8")
        self.assertFalse(self.check_report()["ok"])

    def test_summary_not_eligible_as_direct_quote(self):
        doc = json.loads((self.run / "analysis.json").read_text(encoding="utf-8"))
        doc["evidence"][0]["text_kind"] = "summary"
        self.write("analysis.json", doc)
        self.doc["source_hashes"]["analysis.json"] = self.sha("analysis.json")
        self.write("report-bindings.json", self.doc)
        self.assertFalse(self.check_report()["ok"])

    def test_excluded_source_not_eligible_as_quote(self):
        doc = json.loads((self.run / "analysis.json").read_text(encoding="utf-8"))
        doc["annotations"][0]["status"] = "excluded"
        self.write("analysis.json", doc)
        self.doc["source_hashes"]["analysis.json"] = self.sha("analysis.json")
        self.write("report-bindings.json", self.doc)
        self.assertFalse(self.check_report()["ok"])

    def test_manifest_cannot_invent_its_own_metric_fact(self):
        self.doc["reports"][0]["metrics"][0]["source"] = {"file": "report-bindings.json", "pointer": "/invented"}
        self.write("report-bindings.json", self.doc)
        self.assertFalse(self.check_report()["ok"])

    def test_binding_only_in_script_does_not_count_as_report(self):
        (self.run / "report.html").write_text('<script type="application/json">'+self.html+'</script>', encoding="utf-8")
        self.assertFalse(self.check_report()["ok"])

    def test_required_output_must_be_bound(self):
        self.write("research-spec.json", {"outputs": [{"path": "other.html", "format": "html"}]})
        self.assertFalse(self.check_report()["ok"])

    def test_uppercase_html_output_must_also_be_bound(self):
        self.write("research-spec.json", {"outputs": [{"path": "unbound.html", "format": "HTML"}]})
        self.assertFalse(self.check_report()["ok"])

    def test_outside_source_path_is_rejected(self):
        self.doc["source_hashes"]["../outside.json"] = "0" * 64
        self.write("report-bindings.json", self.doc)
        self.assertFalse(self.check_report()["ok"])


class ArtifactManifestTests(RunFixture):
    def fixture(self):
        for name in ("research-spec.json", "analysis.json", "opinions.json", "report.html"):
            self.write(name, {"source": name})
        return artifact_manifest.snapshot(self.run, [
            ("plan", "research-spec.json"), ("analysis", "analysis.json"),
            ("opinions", "opinions.json"), ("report", "report.html")],
            [("analysis", "plan"), ("opinions", "analysis"), ("report", "opinions")])

    def test_explicit_snapshot_validates(self):
        self.fixture()
        self.assertTrue(artifact_manifest.validate(self.run)["ok"])

    def test_upstream_change_marks_transitive_dependents(self):
        self.fixture()
        self.write("research-spec.json", {"changed": True})
        result = artifact_manifest.validate(self.run)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stale_artifacts"], ["analysis", "opinions", "plan", "report"])
        self.assertEqual(result["summary"]["changed_artifacts"], ["plan"])

    def test_snapshot_cannot_overwrite_previous_version(self):
        self.fixture()
        with self.assertRaises(ValueError):
            artifact_manifest.snapshot(self.run, [("analysis", "analysis.json")])

    def test_path_outside_run_is_rejected(self):
        with self.assertRaises(ValueError):
            artifact_manifest.snapshot(self.run, [("outside", "../outside.json")])

    def test_cycle_is_rejected(self):
        self.write("analysis.json", {})
        self.write("opinions.json", {})
        with self.assertRaises(ValueError):
            artifact_manifest.snapshot(self.run, [("a", "analysis.json"), ("b", "opinions.json")], [("a", "b"), ("b", "a")])

    def test_dependency_hash_cannot_silently_drift(self):
        doc = self.fixture()
        doc["artifacts"][1]["depends_on"][0]["sha256"] = "0" * 64
        self.write("artifact-manifest.json", doc)
        self.assertFalse(artifact_manifest.validate(self.run)["ok"])

    def test_manifest_cannot_include_itself(self):
        self.fixture()
        with self.assertRaises(ValueError):
            artifact_manifest.snapshot(self.run, [("self", "artifact-manifest.json")], output="manifest-v2.json")


if __name__ == "__main__":
    unittest.main()
