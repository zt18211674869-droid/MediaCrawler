"""Check normalized-input coverage and documented full-text review, without editing data.

Usage: python validate_coverage.py RUN_DIR [--output result.json] [--require-complete]
Reads items.jsonl, analysis.json, optional opinions.json and review-ledger.json.
The ledger uses coverage-review-v1, file SHA256 values, review_method, and one
review per evidence ID. Each complete review partitions evidence.text with Python
Unicode character offsets [start, end): opinion/background/irrelevant/uncertain.

Exit 1 on invalid data; --require-complete also exits 1 when strict_ready is false.
Missing historical review records mean review is undocumented, not that nobody
read the material. A valid ledger proves recorded coverage, not correct semantic
judgment. This tool does not enumerate collection responses or verify that a
platform, search window, media item, or conversation was collected in full.
"""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import validate_analysis
import validate_opinions


def digest(data):
    return hashlib.sha256(data).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate(run_dir):
    run = Path(run_dir).resolve()
    errors, warnings = [], []
    result = {
        "ok": False, "strict_ready": False,
        "strict_scope": "normalized_items_to_documented_review",
        "collection_inventory_verified": False,
        "semantic_accuracy_verified": False,
        "review_records_complete": False,
        "semantic_review_documented": False,
        "errors": errors, "warnings": warnings, "summary": {},
    }
    warnings.append("Collection completeness is outside this check; reconcile raw responses separately.")
    warnings.append("Recorded coverage does not prove that every relevant meaning was identified correctly.")
    try:
        items_path, analysis_path = run / "items.jsonl", run / "analysis.json"
        items = [json.loads(line) for line in items_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        analysis = read_json(analysis_path)
        if not isinstance(analysis, dict):
            raise ValueError("analysis must be an object")
    except (OSError, ValueError, TypeError) as exc:
        errors.append(str(exc))
        return result

    def index(rows, label, key="id"):
        found = {}
        if not isinstance(rows, list):
            errors.append(f"{label} must be an array")
            return found
        for row in rows:
            if not isinstance(row, dict) or not nonempty(row.get(key)):
                errors.append(f"{label} needs object rows with nonempty {key}")
                continue
            if row[key] in found:
                errors.append(f"duplicate {label}: {row[key]}")
            found[row[key]] = row
        return found

    evidence = index(analysis.get("evidence"), "evidence")
    annotations = index(analysis.get("annotations"), "annotations", "evidence_id")
    try:
        ae, aw, _ = validate_analysis.validate(analysis, run)
        errors.extend("analysis: " + value for value in ae)
        warnings.extend("analysis: " + value for value in aw)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append("analysis validator could not complete: " + str(exc))

    def identity(row, content_field, label):
        values = (row.get("platform"), row.get(content_field), row.get("unit_id"))
        if not nonempty(values[0]) or not nonempty(values[2]) or not (values[1] is None or nonempty(values[1])):
            errors.append(f"{label}: invalid source identity")
            return None
        return values

    intake, source_evidence = {}, defaultdict(list)
    duplicate_intake_keys = []
    for pos, row in enumerate(items):
        if not isinstance(row, dict):
            errors.append(f"items[{pos}] must be an object")
            continue
        key = identity(row, "content_id", f"items[{pos}]")
        if key is None:
            continue
        if key in intake:
            errors.append(f"duplicate normalized source identity: {key!r}; select a snapshot explicitly")
            duplicate_intake_keys.append(key)
        intake[key] = row
        if not nonempty(row.get("text")):
            errors.append(f"items[{pos}]: normalized text must be nonempty")
        supplied = row.get("content_sha256")
        if supplied is not None and isinstance(row.get("text"), str) and supplied != digest(row["text"].encode("utf-8")):
            errors.append(f"items[{pos}]: content_sha256 mismatch")
    for eid, row in evidence.items():
        key = identity(row, "note_id", eid)
        if key is not None:
            source_evidence[key].append(row)

    missing_sources = set(intake) - set(source_evidence)
    unexpected_sources = set(source_evidence) - set(intake)
    for key in sorted(missing_sources, key=str):
        errors.append(f"normalized source missing from evidence: {key!r}")
    for key in sorted(unexpected_sources, key=str):
        errors.append(f"evidence source missing from normalized input: {key!r}")
    fully_represented, incomplete_text = [], []
    for key in sorted(set(intake) & set(source_evidence), key=str):
        text = intake[key].get("text")
        if not isinstance(text, str) or not text:
            continue
        ranges, ambiguous = [], False
        for row in source_evidence[key]:
            fragment = row.get("text")
            if not isinstance(fragment, str) or not fragment or fragment not in text:
                errors.append(f"{row['id']}: evidence is not a continuous normalized-input substring")
                continue
            explicit = row.get("source_span")
            if explicit is not None:
                start = explicit.get("start") if isinstance(explicit, dict) else None
                end = explicit.get("end") if isinstance(explicit, dict) else None
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or text[start:end] != fragment:
                    errors.append(f"{row['id']}: invalid source_span in normalized input")
                    continue
            else:
                start = text.find(fragment)
                end = start + len(fragment)
                if text.find(fragment, start + 1) != -1:
                    ambiguous = True
                    warnings.append(f"{row['id']}: repeated fragment needs source_span to locate input coverage")
                    continue
            ranges.append((start, end))
        cursor = 0
        for start, end in sorted(ranges):
            if start > cursor:
                break
            cursor = max(cursor, end)
        if cursor == len(text):
            fully_represented.append(key)
        else:
            incomplete_text.append(key)
            warnings.append(f"{key!r}: evidence does not demonstrably cover the entire normalized text" + (" (ambiguous offsets)" if ambiguous else ""))

    opinion_path = run / "opinions.json"
    opinion_doc, opinions, source_reviews = None, {}, {}
    if opinion_path.exists():
        try:
            opinion_doc = read_json(opinion_path)
            if not isinstance(opinion_doc, dict):
                raise ValueError("opinions must be an object")
            opinions = index(opinion_doc.get("opinions"), "opinions")
            source_reviews = index(opinion_doc.get("source_reviews"), "source_reviews", "evidence_id")
            opinion_meta = opinion_doc.get("meta", {})
            if not isinstance(opinion_meta, dict):
                opinion_meta = {}
            # The legacy validator follows source_analysis. Independently bind
            # that layer to THIS run's snapshot, so a valid older snapshot cannot
            # bypass current admission decisions. A byte-identical copy is fine.
            if opinion_meta.get("source_sha256") != digest(analysis_path.read_bytes()):
                errors.append("opinions: source SHA256 does not bind to the current analysis.json")
            checked = validate_opinions.validate(opinion_path)
            errors.extend("opinions: " + value for value in checked["errors"])
            warnings.extend("opinions: " + value for value in checked["warnings"])
            for eid in sorted(set(evidence) - set(source_reviews)):
                errors.append(f"source_reviews missing evidence: {eid}")
            for eid, review in source_reviews.items():
                if eid not in evidence:
                    errors.append(f"source_reviews references evidence outside current analysis: {eid}")
                elif review.get("status") != annotations.get(eid, {}).get("status"):
                    errors.append(f"source_reviews differs from current admission status: {eid}")
            for oid, opinion in opinions.items():
                eid = opinion.get("evidence_id")
                if not isinstance(eid, str) or eid not in evidence:
                    errors.append(f"{oid}: opinion source is outside current analysis")
                    continue
                if annotations.get(eid, {}).get("status") != "admitted":
                    errors.append(f"{oid}: opinion source is not admitted in current analysis")
                quote, source_text = opinion.get("quote"), evidence[eid].get("text")
                if not nonempty(quote) or not isinstance(source_text, str) or quote not in source_text:
                    errors.append(f"{oid}: quote does not match current evidence text")
            # Every opinion must reach an actual final cluster, in both exclusive
            # and multi-label modes. Candidate codes may legitimately be merged
            # or renamed, so they need not equal final cluster IDs.
            clusters = index(opinion_doc.get("clusters"), "clusters")
            memberships = Counter()
            for cluster in clusters.values():
                ids = cluster.get("opinion_ids")
                if isinstance(ids, list):
                    memberships.update(oid for oid in ids if isinstance(oid, str) and oid in opinions)
            for oid in opinions:
                if memberships[oid] == 0:
                    errors.append(f"{oid}: opinion is absent from all final clusters")
                elif opinion_meta.get("cluster_mode") == "primary_exclusive" and memberships[oid] != 1:
                    errors.append(f"{oid}: exclusive classification must assign exactly one final cluster")
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append("opinion validator could not complete: " + str(exc))
    else:
        warnings.append("No independent opinion layer; strict full-opinion review requires opinions.json.")
    opinion_sources = {o.get("evidence_id") for o in opinions.values() if isinstance(o.get("evidence_id"), str)}
    states = Counter(str(annotations.get(eid, {}).get("status", "pending")) for eid in evidence)
    admitted_no_opinions = sorted(eid for eid in evidence if annotations.get(eid, {}).get("status") == "admitted" and eid not in opinion_sources)
    missing_annotations = sorted(set(evidence) - set(annotations))

    ledger_path = run / "review-ledger.json"
    ledger_present, documented, uncertain_sources = ledger_path.exists(), set(), set()
    missing_review_ids = sorted(evidence)
    ledger_valid = False
    pending_reviews, outcome_counts, used_opinions = [], Counter(), set()
    if ledger_present:
        before_ledger = len(errors)
        try:
            ledger = read_json(ledger_path)
            if not isinstance(ledger, dict):
                raise ValueError("review-ledger must be an object")
            if ledger.get("schema_version") != "coverage-review-v1":
                errors.append("ledger schema_version must be coverage-review-v1")
            if not nonempty(ledger.get("review_method")):
                errors.append("ledger review_method must state the actual review method")
            expected_hashes = {
                "source_items_sha256": digest(items_path.read_bytes()),
                "source_analysis_sha256": digest(analysis_path.read_bytes()),
                "source_opinions_sha256": digest(opinion_path.read_bytes()) if opinion_path.exists() else None,
            }
            for field, expected in expected_hashes.items():
                if field not in ledger or ledger[field] != expected:
                    errors.append(f"ledger {field} mismatch")
            reviews = index(ledger.get("reviews"), "ledger reviews", "evidence_id")
            missing_review_ids = sorted(set(evidence) - set(reviews))
            for eid in missing_review_ids:
                errors.append(f"ledger review missing evidence: {eid}")
            for eid in sorted(set(reviews) - set(evidence)):
                errors.append(f"ledger review references unknown evidence: {eid}")
            for eid in sorted(set(reviews) & set(evidence)):
                row, text = reviews[eid], evidence[eid].get("text")
                start_errors = len(errors)
                if not isinstance(text, str):
                    continue
                if row.get("text_sha256") != digest(text.encode("utf-8")):
                    errors.append(f"{eid}: ledger text_sha256 mismatch")
                if row.get("assessor") not in {"model", "human", "mixed"}:
                    errors.append(f"{eid}: ledger assessor must describe actual participation")
                status = row.get("review_status")
                if status not in {"pending", "complete"}:
                    errors.append(f"{eid}: invalid review_status")
                if status != "complete":
                    pending_reviews.append(eid)
                segments = row.get("segments")
                if not isinstance(segments, list):
                    errors.append(f"{eid}: segments must be an array")
                    continue
                ranges = []
                for n, segment in enumerate(segments):
                    label = f"{eid}.segments[{n}]"
                    if not isinstance(segment, dict):
                        errors.append(f"{label}: must be an object")
                        continue
                    start, end = segment.get("start"), segment.get("end")
                    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                        errors.append(f"{label}: invalid half-open character interval")
                        continue
                    ranges.append((start, end))
                    outcome, refs = segment.get("outcome"), segment.get("opinion_ids")
                    if outcome not in {"opinion", "background", "irrelevant", "uncertain"}:
                        errors.append(f"{label}: invalid outcome")
                    else:
                        outcome_counts[outcome] += 1
                    if outcome == "uncertain":
                        uncertain_sources.add(eid)
                    if not nonempty(segment.get("reason")):
                        errors.append(f"{label}: needs a source-specific reason (meaning must be reviewed separately)")
                    if not isinstance(refs, list) or any(not nonempty(oid) for oid in refs):
                        errors.append(f"{label}: opinion_ids must be an array of IDs")
                        continue
                    if len(refs) != len(set(refs)):
                        errors.append(f"{label}: duplicate opinion references")
                    if outcome == "opinion" and not refs:
                        errors.append(f"{label}: opinion outcome needs at least one opinion")
                    if outcome != "opinion" and refs:
                        errors.append(f"{label}: non-opinion outcome must have empty opinion_ids")
                    for oid in refs:
                        opinion = opinions.get(oid)
                        if opinion is None or opinion.get("evidence_id") != eid:
                            errors.append(f"{label}: opinion {oid} does not belong to this evidence")
                            continue
                        quote = opinion.get("quote")
                        if not nonempty(quote) or quote not in text[start:end]:
                            errors.append(f"{label}: opinion {oid} quote is outside the reviewed segment")
                        used_opinions.add(oid)
                cursor = 0
                for start, end in sorted(ranges):
                    if start < cursor:
                        errors.append(f"{eid}: review segments overlap")
                    if status == "complete" and start > cursor:
                        errors.append(f"{eid}: review segments leave an unreviewed gap")
                    cursor = max(cursor, end)
                if status == "complete" and cursor != len(text):
                    errors.append(f"{eid}: review segments do not cover the full text")
                if status == "complete" and start_errors == len(errors):
                    documented.add(eid)
            for oid in sorted(set(opinions) - used_opinions):
                errors.append(f"opinion missing from review segments: {oid}")
            ledger_valid = before_ledger == len(errors)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append("ledger validation could not complete: " + str(exc))
    else:
        warnings.append("No review-ledger.json: full-text semantic review is undocumented; this does not establish that the material was unread.")

    records_complete = bool(evidence) and ledger_valid and documented == set(evidence)
    structure_complete = bool(intake) and not missing_sources and not unexpected_sources and not duplicate_intake_keys and len(items) == len(intake) == len(source_evidence)
    result.update({
        "ok": not errors,
        "structurally_accounted": structure_complete,
        "review_records_complete": records_complete,
        "semantic_review_documented": records_complete,
        "strict_ready": bool(not errors and structure_complete and len(fully_represented) == len(intake)
                             and records_complete and opinion_doc is not None
                             and not states["pending"] and not states["uncertain"] and not uncertain_sources),
        "summary": {
            "normalized_input_rows": len(items), "normalized_source_units": len(intake),
            "duplicate_normalized_source_keys": [list(key) for key in duplicate_intake_keys],
            "intake_evidence_units": len(evidence), "evidence_source_units": len(source_evidence),
            "missing_input_sources": [list(key) for key in sorted(missing_sources, key=str)],
            "unexpected_evidence_sources": [list(key) for key in sorted(unexpected_sources, key=str)],
            "full_input_text_represented_units": len(fully_represented),
            "incomplete_input_text_units": [list(key) for key in incomplete_text],
            "annotation_counts": dict(states), "missing_annotation_ids": missing_annotations,
            "opinion_count": len(opinions), "opinion_source_count": len(opinion_sources & set(evidence)),
            "admitted_without_opinions_count": len(admitted_no_opinions),
            "admitted_without_opinions_ids": admitted_no_opinions,
            "ledger_present": ledger_present, "documented_complete_review_count": len(documented) if ledger_valid else 0,
            "review_not_documented_count": len(evidence) - (len(documented) if ledger_valid else 0),
            "missing_review_ids": missing_review_ids, "pending_review_ids": pending_reviews,
            "uncertain_segment_source_ids": sorted(uncertain_sources), "review_segment_outcomes": dict(outcome_counts),
        },
    })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    result = validate(args.run_dir)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if result["errors"] or (args.require_complete and not result["strict_ready"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
