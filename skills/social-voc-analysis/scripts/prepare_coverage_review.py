"""Prepare full-text review batches and a pending ledger; never certify reading.

python prepare_coverage_review.py RUN_DIR [--output-dir DIR]
Only the standard library is needed. Existing work files are not overwritten.
Batch limits control work size, not analysis scope; oversized sources stay whole.
"""
import argparse
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(value).hexdigest()


def prepare(run_dir, output_dir=None, max_chars=12000, max_sources=25):
    run_dir = Path(run_dir).resolve()
    output_dir = Path(output_dir).resolve() if output_dir else run_dir
    if max_chars < 1 or max_sources < 1:
        raise ValueError("Batch limits must be positive")
    paths = {name: run_dir / name for name in ("items.jsonl", "analysis.json", "opinions.json")}
    hashes = {name: digest(path.read_bytes()) if path.exists() else None for name, path in paths.items()}
    if hashes["items.jsonl"] is None or hashes["analysis.json"] is None:
        raise ValueError("items.jsonl and analysis.json are required")
    analysis = json.loads(paths["analysis.json"].read_text(encoding="utf-8-sig"))
    opinion_doc = json.loads(paths["opinions.json"].read_text(encoding="utf-8-sig")) if hashes["opinions.json"] else {}
    evidence = analysis.get("evidence", [])
    if not evidence:
        raise ValueError("No evidence to review")
    seen = set()
    annotations = {a["evidence_id"]: a for a in analysis.get("annotations", [])}
    by_source = {}
    for opinion in opinion_doc.get("opinions", []):
        by_source.setdefault(opinion["evidence_id"], []).append(opinion)
    rows, reviews = [], []
    for source in evidence:
        eid, text = source.get("id"), source.get("text")
        if not isinstance(eid, str) or not eid or eid in seen:
            raise ValueError("Missing or duplicate evidence ID")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{eid}: evidence needs nonempty text")
        seen.add(eid)
        rows.append({"evidence_id": eid, "source": source,
                     "existing_annotation": annotations.get(eid),
                     "existing_opinions": by_source.get(eid, []),
                     "instruction": "阅读完整文字，检查全部相关观点；保留具体零观点原因及歧义，不照抄旧标签当作复核。"})
        reviews.append({"evidence_id": eid, "text_sha256": digest(text.encode("utf-8")),
                        "review_status": "pending", "assessor": "model", "segments": []})
    batches, current, size = [], [], 0
    for row in rows:
        # Include context/opinions in the budget so long annotations do not hide work.
        length = len(json.dumps(row, ensure_ascii=False))
        if current and (len(current) >= max_sources or size + length > max_chars):
            batches.append(current)
            current, size = [], 0
        current.append(row)
        size += length
    if current:
        batches.append(current)
    ledger = {"schema_version": "coverage-review-v1",
              "source_items_sha256": hashes["items.jsonl"],
              "source_analysis_sha256": hashes["analysis.json"],
              "source_opinions_sha256": hashes["opinions.json"],
              "review_method": "待逐批回看全部原文并记录逐段处理；本文件由工具准备，尚未执行复核。",
              "reviews": reviews}
    outputs = {"review-ledger.json": ledger}
    manifest = {"source_files": hashes, "evidence_count": len(rows),
                "max_chars": max_chars, "max_sources": max_sources,
                "meaning": "分批工作清单，不是分析或复核完成证明。", "batches": []}
    for index, batch in enumerate(batches, 1):
        name = f"coverage-batches/batch-{index:04d}.json"
        doc = {"source_files": hashes, "batch_id": f"batch-{index:04d}", "sources": batch}
        outputs[name] = doc
        manifest["batches"].append({"file": name, "evidence_ids": [r["evidence_id"] for r in batch],
                                    "oversized_single_source": len(batch) == 1 and len(json.dumps(batch[0], ensure_ascii=False)) > max_chars})
    outputs["coverage-batches/manifest.json"] = manifest
    for name in outputs:
        if (output_dir / name).exists():
            raise FileExistsError(f"Refusing to overwrite: {output_dir / name}")
    for name, doc in outputs.items():
        target = output_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return {"sources": len(rows), "batches": len(batches), "all_pending": True,
            "output_dir": str(output_dir)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--max-sources", type=int, default=25)
    args = parser.parse_args()
    try:
        result = prepare(args.run_dir, args.output_dir, args.max_chars, args.max_sources)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Preparation failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
