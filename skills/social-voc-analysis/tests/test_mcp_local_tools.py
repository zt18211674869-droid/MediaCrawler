"""Offline synthetic MCP wrappers test local provenance and recovery invariants."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collection_ledger as ledger
from normalize_mcp import normalize
from prepare_analysis import prepare
from validate_analysis import pointer_get


class MCPToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".voc-mcp-test-", dir=Path.cwd())
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.response = self.base / "response.json"
        self.mapping = self.base / "map.json"
        self.run = self.base / "run"
        self.rows = [{"id": "900719925474099312345", "body": "很方便，但导出仍慢。", "likes": 3},
                     {"id": "2", "body": "", "likes": 0}]
        self.map = {"schema_version": "mcp-mapping-v1", "provider": "guaikei", "run_id": "synthetic-test",
                    "mapping_version": "synthetic-v1", "mapping_basis": "Synthetic wrapper for offline tests; not a live MCP capture.",
                    "collected_at": "2026-11-10T10:00:00+08:00", "payload": {"pointer": "/content/0/text", "decode_json": True},
                    "records_pointer": "/notes", "fields": {"platform": {"literal": "xiaohongshu"}, "content_id": {"pointer": "/id"},
                    "unit_id": {"literal": "body"}, "unit_type": {"literal": "note"}, "text_kind": {"literal": "full_text"},
                    "text": {"pointer": "/body"}, "url": {"literal": None}, "published_at": {"literal": None}},
                    "metrics": {"likes": {"pointer": "/likes", "unit": "次"}}}

    def write(self, direct=False):
        wrapper = {"structuredContent": {"notes": self.rows}} if direct else {"content": [{"type": "text", "text": json.dumps({"notes": self.rows}, ensure_ascii=False)}]}
        self.response.write_text(json.dumps(wrapper, ensure_ascii=False), encoding="utf-8")
        self.mapping.write_text(json.dumps(self.map, ensure_ascii=False), encoding="utf-8")

    def test_decoded_original_and_counts_survive_prepare(self):
        self.write()
        original = self.response.read_bytes()
        result = normalize(self.response, self.mapping, self.run)
        self.assertEqual(result["coverage"], {"raw_records": 2, "selected_records": 1, "missing_text": 1, "duplicate": 0, "excluded": 0})
        self.assertEqual((self.run / "raw/mcp-response.json").read_bytes(), original)
        evidence = prepare(self.run)["evidence"][0]
        self.assertEqual(evidence["note_id"], "900719925474099312345")
        ref = evidence["raw_ref"]
        self.assertEqual(pointer_get(json.loads((self.run / ref["file"]).read_text(encoding="utf-8")), ref["pointer"]), self.rows[0]["body"])
        self.assertEqual(evidence["metrics"]["likes"], {"raw": 3, "value": 3, "unit": "次"})
        self.assertFalse((self.run / "analysis.json").exists())

    def test_direct_structured_content_and_summary_type(self):
        self.map["payload"] = {"pointer": "/structuredContent", "decode_json": False}
        self.map["fields"]["text_kind"] = {"literal": "summary"}
        self.write(direct=True)
        normalize(self.response, self.mapping, self.run)
        evidence = prepare(self.run)["evidence"][0]
        self.assertEqual(evidence["text_kind"], "summary")
        self.assertEqual(evidence["raw_ref"]["pointer"], "/structuredContent/notes/0/body")

    def test_float_id_and_unknown_shape_rejected_without_run(self):
        self.rows[0]["id"] = 9.007199254740993e20
        self.write()
        with self.assertRaises(ValueError):
            normalize(self.response, self.mapping, self.run)
        self.assertFalse(self.run.exists())
        self.rows[0]["id"] = "1"
        self.map["payload"]["pointer"] = "/missing"
        self.write()
        with self.assertRaises(ValueError):
            normalize(self.response, self.mapping, self.run)

    def test_existing_run_and_non_guaikei_mapping_rejected(self):
        self.write()
        normalize(self.response, self.mapping, self.run)
        before = (self.run / "items.jsonl").read_bytes()
        with self.assertRaises(ValueError):
            normalize(self.response, self.mapping, self.run)
        self.assertEqual((self.run / "items.jsonl").read_bytes(), before)
        self.map["provider"] = "other"
        self.write()
        with self.assertRaises(ValueError):
            normalize(self.response, self.mapping, self.base / "other")

    def test_exclusions_duplicates_conflicts_and_empty_records_accounted(self):
        self.rows += [copy.deepcopy(self.rows[0]), {"advert": "out of scope"}]
        self.map["excluded_records"] = [{"index": 3, "reason": "Outside the declared research window."}]
        self.write()
        result = normalize(self.response, self.mapping, self.run)
        self.assertEqual(result["coverage"]["duplicate"], 1)
        inventory = json.loads((self.run / "raw-inventory.json").read_text(encoding="utf-8"))
        self.assertEqual([r["disposition"] for r in inventory["records"]], ["selected", "missing_text", "duplicate", "excluded"])
        self.rows[2]["body"] = "edited content"
        self.write()
        with self.assertRaises(ValueError):
            normalize(self.response, self.mapping, self.base / "conflict")

    def request(self, rid="r1", keyword="测试"):
        return {"request_id": rid, "tool": "xiaohongshu_note_search", "parameters": {"keyword": keyword, "limit": 50}, "target_count": 50, "effective_limit": 50}

    def initialize_ledger(self, calls=3):
        ledger.init(self.run, 50, 2, calls)
        ledger.record(self.run, self.request())

    def test_duplicate_request_and_non_guaikei_rejected(self):
        self.initialize_ledger()
        with self.assertRaises(ValueError):
            ledger.record(self.run, self.request("different-id"))
        with self.assertRaises(ValueError):
            ledger.record(self.run, {**self.request("r2", "new"), "provider": "other"})
        with self.assertRaises(ValueError):
            ledger.init(self.run, 50, 2, 3)
        self.assertEqual(ledger.status(self.run)["task_count"], 1)

    def test_unknown_submission_requires_query_evidence_and_no_resubmit(self):
        self.initialize_ledger()
        ledger.transition(self.run, "r1", {"state": "submission_unknown", "action": "submit", "reason": "Host lost response after submission."})
        with self.assertRaises(ValueError):
            ledger.transition(self.run, "r1", {"state": "submitted_pending", "action": "submit", "reason": "Retry"})
        with self.assertRaises(ValueError):
            ledger.transition(self.run, "r1", {"state": "complete", "action": "query", "query_supported": True, "reason": "A query was available."})
        (self.run / "query.json").write_text('{"state":"complete","data":[]}', encoding="utf-8")
        row = ledger.transition(self.run, "r1", {"state": "complete", "action": "query", "query_supported": True, "reason": "Actual query returned a valid empty result.", "result_ref": {"file": "query.json"}, "returned_count": 0})
        self.assertEqual(row["state"], "complete")
        self.assertIsNone(ledger.status(self.run)["http_requests"])
        self.assertEqual(ledger.status(self.run)["tool_calls"], 2)
        (self.run / "query.json").write_text('{"changed":true}', encoding="utf-8")
        with self.assertRaises(ValueError):
            ledger.status(self.run)

    def test_budget_and_result_path_checks_preserve_previous_state(self):
        self.initialize_ledger(calls=1)
        ledger.transition(self.run, "r1", {"state": "submitted_pending", "action": "submit", "reason": "MCP accepted task."})
        before = (self.run / "collection-ledger.json").read_bytes()
        with self.assertRaises(ValueError):
            ledger.transition(self.run, "r1", {"state": "complete", "action": "query", "query_supported": True, "reason": "Would exceed budget.", "result_ref": {"file": "../outside.json"}})
        self.assertEqual((self.run / "collection-ledger.json").read_bytes(), before)
        (self.base / "outside.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            ledger.result_reference(self.run, {"file": "../outside.json"})
        ledger.record(self.run, self.request("r2", "second"))
        with self.assertRaises(ValueError):
            ledger.record(self.run, self.request("r3", "third"))

    def test_credentials_and_missing_completion_evidence_rejected(self):
        self.initialize_ledger()
        with self.assertRaises(ValueError):
            ledger.record(self.run, {**self.request("r2", "new"), "parameters": {"api_key": "dummy-only"}})
        with self.assertRaises(ValueError):
            ledger.transition(self.run, "r1", {"state": "complete", "action": "submit", "reason": "No stored output."})
        self.assertEqual(ledger.status(self.run)["tool_calls"], 0)


if __name__ == "__main__":
    unittest.main()
