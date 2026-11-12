"""Validate the optional opinion layer against its frozen evidence snapshot.

Usage: python validate_opinions.py /path/to/opinions.json
Only structural, provenance and counting invariants are checked, not meaning.
"""
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import research_plan


def validate(path):
    path = Path(path)
    errors, warnings = [], []
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(doc, dict):
            raise ValueError("opinion document must be an object")
        meta = doc.get("meta", {})
        if not isinstance(meta, dict):
            raise ValueError("meta must be an object")
        source = (path.parent / meta["source_analysis"]).resolve()
        raw = source.read_bytes()
        analysis = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"errors": [str(exc)], "warnings": [], "summary": {}}
    if meta.get("schema_version") != "opinions-v1":
        errors.append("meta.schema_version must be opinions-v1")
    if meta.get("source_sha256") != hashlib.sha256(raw).hexdigest():
        errors.append("source snapshot SHA256 mismatch")
    if not isinstance(meta.get("coding_version"), str) or not meta["coding_version"].strip():
        errors.append("meta.coding_version is required")
    try:
        dt = datetime.fromisoformat(meta["analysis_as_of"].replace("Z", "+00:00"))
        if dt.utcoffset() is None:
            raise ValueError("timezone missing")
    except (KeyError, ValueError, TypeError, AttributeError):
        errors.append("meta.analysis_as_of must be a dated timestamp with timezone")

    def indexed(rows, label, key="id"):
        result = {}
        if not isinstance(rows, list):
            errors.append(f"{label} must be an array")
            return result
        for i, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key].strip():
                errors.append(f"{label}[{i}] needs a nonempty {key}")
                continue
            rid = row[key]
            if rid in result:
                errors.append(f"duplicate {label} ID: {rid}")
            result[rid] = row
        return result

    evidence = indexed(analysis.get("evidence"), "source evidence")
    annotations = indexed(analysis.get("annotations"), "source annotations", "evidence_id")
    reviews = indexed(doc.get("source_reviews"), "source_reviews", "evidence_id")
    opinions = indexed(doc.get("opinions"), "opinions")
    clusters = indexed(doc.get("clusters"), "clusters")
    findings = indexed(doc.get("findings"), "findings")
    question_ids_in_plan = None
    plan_path = path.parent / "research-spec.json"
    if plan_path.exists():
        checked_plan = research_plan.validate(plan_path)
        errors.extend("research-spec: " + x for x in checked_plan["errors"])
        warnings.extend(checked_plan["warnings"])
        question_ids_in_plan = ({row["id"] for row in checked_plan["plan"].get("question_plan", [])
                                 if isinstance(row, dict) and isinstance(row.get("id"), str)}
                                if checked_plan["ok"] else set())
    else:
        warnings.append("No research-spec.json; finding-to-question links were not checked.")
    complete = meta.get("review_complete") is True
    if complete and set(reviews) != set(evidence):
        errors.append("complete review must cover every source evidence exactly once")
    elif not complete:
        warnings.append("Source review is partial; disclose coverage.")
    if complete and any(r.get("status") == "pending" for r in reviews.values()):
        errors.append("complete review cannot retain pending source reviews")

    def refs(row, key, pool, label):
        values = row.get(key)
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            errors.append(f"{label}.{key} must be a string array")
            return []
        if len(values) != len(set(values)):
            errors.append(f"{label}.{key} contains duplicate references")
        for value in values:
            if value not in pool:
                errors.append(f"{label}.{key} references unknown ID: {value}")
        return [x for x in values if x in pool]

    def text_field(row, key, label):
        if not isinstance(row.get(key), str) or not row[key].strip():
            errors.append(f"{label}.{key} must be nonempty text")

    for eid, row in reviews.items():
        if eid not in evidence:
            errors.append(f"review references unknown source: {eid}")
            continue
        e = evidence[eid]
        if row.get("source_key") != (e.get("display_key") or e["id"]):
            errors.append(f"review source_key mismatch: {eid}")
        if row.get("status") != annotations.get(eid, {}).get("status"):
            errors.append(f"review silently changes frozen admission status: {eid}")
        text_field(row, "reason", eid)
        ids = refs(row, "opinion_ids", opinions, eid)
        if set(ids) != {oid for oid, o in opinions.items() if o.get("evidence_id") == eid}:
            errors.append(f"review opinion coverage mismatch: {eid}")

    for oid, o in opinions.items():
        eid = o.get("evidence_id")
        if not isinstance(eid, str) or eid not in evidence:
            errors.append(f"{oid}: unknown evidence_id")
            continue
        e = evidence[eid]
        if eid not in reviews:
            errors.append(f"{oid}: source lacks review")
        if annotations.get(eid, {}).get("status") != "admitted":
            errors.append(f"{oid}: opinion uses a source not admitted")
        if o.get("source_key") != (e.get("display_key") or e["id"]):
            errors.append(f"{oid}: source_key mismatch")
        for field in ("product", "aspect", "statement", "quote", "candidate_theme"):
            text_field(o, field, oid)
        quote = o.get("quote")
        if isinstance(quote, str) and quote and quote not in e.get("text", ""):
            errors.append(f"{oid}: quote is not a continuous original substring")
        if e.get("text_kind") in {"summary", "rewritten", "unknown"}:
            errors.append(f"{oid}: source text cannot support a verbatim quote")
        if o.get("polarity") not in {"positive", "negative", "neutral", "mixed"}:
            errors.append(f"{oid}: invalid polarity")
        if o.get("kind") not in {"self_report", "help", "recommendation", "tutorial", "vendor_claim", "expectation", "question", "context"}:
            errors.append(f"{oid}: invalid kind")
        if o.get("evidence_role") not in {"experience", "supply", "context"}:
            errors.append(f"{oid}: invalid evidence_role")
        if o.get("kind") == "vendor_claim" and o.get("evidence_role") == "experience":
            errors.append(f"{oid}: vendor claim cannot be treated as experience evidence")
        for field in ("scene", "journey_stage", "behavior", "expectation", "consequence", "limits"):
            if field not in o or (o[field] is not None and (not isinstance(o[field], str) or not o[field].strip())):
                errors.append(f"{oid}.{field} must be nonempty text or null")

    def counts(ids):
        es = {opinions[x]["evidence_id"] for x in ids if isinstance(opinions[x].get("evidence_id"), str) and opinions[x]["evidence_id"] in evidence}
        units = {(evidence[x].get("platform"), evidence[x].get("note_id"), evidence[x].get("unit_id") or x) for x in es}
        works = {(evidence[x].get("platform"), evidence[x]["note_id"]) for x in es if evidence[x].get("note_id")}
        authors = {(evidence[x].get("platform"), evidence[x]["author_id"]) for x in es if evidence[x].get("author_id")}
        return {"opinion_count": len(set(ids)), "source_count": len(units), "work_count": len(works), "author_count": len(authors)}

    membership = Counter()
    cluster_stats = {}
    for cid, c in clusters.items():
        for field in ("title", "definition"):
            text_field(c, field, cid)
        ids = refs(c, "opinion_ids", opinions, cid)
        if not ids:
            errors.append(f"{cid}: empty cluster")
        membership.update(ids)
        stats = counts(ids)
        cluster_stats[cid] = stats
        for key, value in stats.items():
            if key in c and (type(c[key]) is not int or c[key] != value):
                errors.append(f"{cid}.{key} differs from frozen opinions")
    if meta.get("cluster_mode") == "primary_exclusive":
        if set(membership) != set(opinions) or any(n != 1 for n in membership.values()):
            errors.append("primary_exclusive clusters must partition all opinions exactly once")

    finding_stats = {}
    for fid, f in findings.items():
        for field in ("claim", "interpretation", "limits"):
            text_field(f, field, fid)
        support = refs(f, "support_opinion_ids", opinions, fid)
        counter = refs(f, "counter_opinion_ids", opinions, fid)
        if "boundary_opinion_ids" in f:
            refs(f, "boundary_opinion_ids", opinions, fid)
        if not support:
            errors.append(f"{fid}: finding has no supporting opinions")
        if set(support) & set(counter):
            errors.append(f"{fid}: same opinion listed as support and counter")
        question_ids = f.get("question_ids")
        if not isinstance(question_ids, list) or not question_ids or any(not isinstance(x, str) or not x.strip() for x in question_ids):
            errors.append(f"{fid}: question_ids must be a nonempty string array")
        elif question_ids_in_plan is not None and not set(question_ids) <= question_ids_in_plan:
            errors.append(f"{fid}: question_ids reference questions absent from research-spec")
        finding_stats[fid] = {"support": counts(support), "counter": counts(counter)}
    return {"errors": errors, "warnings": warnings,
            "summary": {"sources": len(evidence), "reviewed": len(reviews), "opinions": len(opinions),
                        "polarity": dict(Counter(o.get("polarity") for o in opinions.values())),
                        "roles": dict(Counter(o.get("evidence_role") for o in opinions.values())),
                        "clusters": cluster_stats, "findings": finding_stats}}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate_opinions.py <opinions.json>", file=sys.stderr)
        raise SystemExit(2)
    result = validate(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result["errors"] else 0)
