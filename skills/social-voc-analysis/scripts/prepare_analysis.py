"""Create a pending analysis snapshot from a collection package, without coding it.

Uses only the standard library. Existing snapshots are never overwritten.
Run: python prepare_analysis.py RUN_DIR [--output analysis.json]
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from validate_analysis import validate


def prepare(run_dir):
    run_dir = Path(run_dir).resolve()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("run_id"), str) or not manifest["run_id"].strip():
        raise ValueError("manifest needs a non-empty run_id")
    mode = manifest.get("collection_mode")
    if mode not in ("offline", "mcp", "cli", "mixed"):
        raise ValueError("manifest.collection_mode must explicitly be offline, mcp, cli or mixed")
    result = {
        "meta": {
            "run_id": manifest["run_id"], "collection_mode": mode,
            "coding_version": "v1", "analysis_as_of": datetime.now(timezone.utc).isoformat(),
            "research_question": manifest.get("research_question"),
            "source_manifest": "manifest.json", "stage": "pending_coding",
        },
        "evidence": [], "annotations": [], "findings": [],
    }
    ids, sources, missing_text = {}, {}, []
    optional = (
        "unit_type", "text_kind", "title", "author_id", "author_name", "parent_unit_id",
        "metrics", "published_at_raw", "published_at_basis", "provenance_layer", "profile",
        "source_version", "record_ref", "raw_fields", "missing_metadata", "imported_at",
        "raw_field", "raw_time", "time_source", "time_unit", "content_sha256",
        "source_caption", "unmapped_metrics", "content_id_origin", "source_snapshot",
        "capture_layer", "id_origin", "source_file", "task_id", "provider_task_id", "source_sha256",
    )
    input_rows = 0
    for number, line in enumerate((run_dir / "items.jsonl").read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        input_rows += 1
        if not isinstance(row, dict):
            raise ValueError(f"items line {number}: expected object")
        for field in ("platform", "content_id", "unit_id"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"items line {number}: non-empty string {field} required")
        if row.get("unit_type") not in ("note", "comment", "reply", "transcript"):
            raise ValueError(f"items line {number}: unsupported unit_type")
        if row.get("text_kind") not in ("full_text", "summary", "transcript", "rewritten", "unknown"):
            raise ValueError(f"items line {number}: unsupported text_kind")
        text = row.get("text")
        if text is None or text == "" or (isinstance(text, str) and not text.strip()):
            missing_text.append({"line": number, "platform": row["platform"], "content_id": row["content_id"], "unit_id": row["unit_id"]})
            continue
        if not isinstance(text, str):
            raise ValueError(f"items line {number}: text must be string or null")
        identity = (row["platform"], row["content_id"], row["unit_id"])
        # A refreshed/edited source must be selected explicitly before coding.
        if identity in sources and sources[identity] != text:
            raise ValueError(f"items line {number}: conflicting source versions; select a snapshot or separate summary/body unit identities")
        sources[identity] = text
        fingerprint = json.dumps([*identity, text], ensure_ascii=False, separators=(",", ":"))
        eid = "E-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
        evidence = {
            "id": eid, "platform": row["platform"], "note_id": row["content_id"],
            "unit_id": row["unit_id"], "text": text,
        }
        for field in ("published_at", "collected_at", "url", "raw_ref"):
            if field not in row:
                raise ValueError(f"items line {number}: missing {field}")
            evidence[field] = row[field]
        for field in optional:
            if field in row:
                evidence[field] = row[field]
        # Validate every source reference, even if its passage is a duplicate.
        check = {"meta": result["meta"], "evidence": [evidence], "annotations": [], "findings": []}
        errors, _, _ = validate(check, run_dir)
        if errors:
            raise ValueError(f"items line {number}: " + "; ".join(errors))
        if eid in ids:
            existing = ids[eid]
            if (existing.get("text_kind"), existing.get("unit_type")) != (evidence.get("text_kind"), evidence.get("unit_type")):
                raise ValueError(f"items line {number}: duplicate source has contradictory text provenance")
            # File relocation is not a new snapshot, but changed capture times,
            # metrics or any other source metadata require an explicit choice.
            def snapshot_content(item):
                ignored = {"raw_ref", "record_ref", "raw_field", "raw_fields", "additional_raw_refs", "additional_source_refs"}
                return {key: value for key, value in item.items() if key not in ignored}

            if snapshot_content(existing) != snapshot_content(evidence):
                raise ValueError(f"items line {number}: source snapshot metadata differs; select one snapshot explicitly before coding")
            extra = {key: evidence[key] for key in ("raw_ref", "record_ref", "raw_field", "raw_fields") if key in evidence}
            existing.setdefault("additional_raw_refs", []).append(evidence["raw_ref"])
            existing.setdefault("additional_source_refs", []).append(extra)
            continue
        ids[eid] = evidence
        result["evidence"].append(evidence)
        result["annotations"].append({
            "evidence_id": eid, "status": "pending", "reason": "Awaiting relevance and research coding; imported only.",
            "assessor": "model", "coding_version": "v1",
        })
    result["meta"]["import_coverage"] = {"input_rows": input_rows, "evidence_rows": len(ids), "without_usable_text": missing_text}
    errors, warnings, _ = validate(result, run_dir)
    if errors:
        raise ValueError("; ".join(errors))
    result["meta"]["validation_warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", default="analysis.json", help="filename inside RUN_DIR")
    args = parser.parse_args()
    try:
        if Path(args.output).name != args.output or args.output in ("", ".", ".."):
            raise ValueError("output must be a filename in RUN_DIR")
        result = prepare(args.run_dir)
        destination = args.run_dir / args.output
        with destination.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"ok": True, "stage": "pending_coding", "evidence": len(result["evidence"]), "output": str(destination)}))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
