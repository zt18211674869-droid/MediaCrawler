import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_coverage_review as MODULE


class PreparationTests(unittest.TestCase):
    def test_every_source_once_with_complete_unicode_text_and_pending_status(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            texts = ["安全👍；售后一般。", "长文" * 1000, "背景说明。"]
            evidence = [{"id": f"E{i}", "text": text} for i, text in enumerate(texts)]
            (run / "items.jsonl").write_text("{}\n", encoding="utf-8")
            (run / "analysis.json").write_text(json.dumps({"evidence": evidence, "annotations": []}), encoding="utf-8")
            original = (run / "analysis.json").read_bytes()
            result = MODULE.prepare(run, max_chars=500, max_sources=2)
            manifest = json.loads((run / "coverage-batches/manifest.json").read_text(encoding="utf-8"))
            flattened = [r["source"] for b in manifest["batches"] for r in json.loads((run / b["file"]).read_text(encoding="utf-8"))["sources"]]
            self.assertEqual(flattened, evidence)
            self.assertEqual(result["sources"], 3)
            self.assertTrue(any(b["oversized_single_source"] for b in manifest["batches"]))
            ledger = json.loads((run / "review-ledger.json").read_text(encoding="utf-8"))
            self.assertTrue(all(r["review_status"] == "pending" and r["segments"] == [] for r in ledger["reviews"]))
            self.assertEqual(original, (run / "analysis.json").read_bytes())

    def test_refuses_to_replace_existing_review(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            (run / "items.jsonl").write_text("{}\n", encoding="utf-8")
            (run / "analysis.json").write_text(json.dumps({"evidence": [{"id": "E", "text": "原文"}]}), encoding="utf-8")
            (run / "review-ledger.json").write_text("existing review", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                MODULE.prepare(run)
            self.assertEqual((run / "review-ledger.json").read_text(encoding="utf-8"), "existing review")
            self.assertFalse((run / "coverage-batches").exists())

    def test_duplicate_id_is_not_silently_collapsed(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            (run / "items.jsonl").write_text("{}\n", encoding="utf-8")
            (run / "analysis.json").write_text(json.dumps({"evidence": [{"id": "E", "text": "一"}, {"id": "E", "text": "二"}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.prepare(run)
            self.assertFalse((run / "review-ledger.json").exists())


if __name__ == "__main__":
    unittest.main()
