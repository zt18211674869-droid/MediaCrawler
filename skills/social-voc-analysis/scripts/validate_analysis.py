"""Validate a frozen VOC analysis snapshot without changing source data.

Usage: python validate_analysis.py <run-dir>/analysis.json
Standard library only. Exit 1 on invalid links/counts, 2 on unreadable input.
This checks provenance and arithmetic, not the meaning of a research claim.
"""
import argparse
import json
import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path


def valid_iso_time(value, allow_date=False):
    if not isinstance(value, str):
        return False
    try:
        if allow_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
            return True
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
            return False
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.utcoffset() is not None
    except ValueError:
        return False


def nonnegative_number(value):
    return type(value) in (int, float) and value >= 0 and (not isinstance(value, float) or math.isfinite(value))


def valid_json_value(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(valid_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and valid_json_value(item) for key, item in value.items())
    return False


def valid_metric(value):
    if value is None or nonnegative_number(value):
        return True
    if not isinstance(value, dict) or "raw" not in value or "value" not in value:
        return False
    raw = value["raw"]
    if not valid_json_value(raw):
        return False
    number = value["value"]
    if number is not None:
        if not nonnegative_number(number):
            return False
        if nonnegative_number(raw):
            expected = raw
        elif isinstance(raw, str) and re.fullmatch(r"\d+(?:\.\d+)?", raw):
            try:
                expected = float(raw) if "." in raw else int(raw)
            except ValueError:
                return False
        else:
            return False
        if expected != number:
            return False
    return "unit" not in value or (isinstance(value["unit"], str) and bool(value["unit"].strip()))


def same_json_value(left, right):
    """Compare JSON values without treating booleans as numbers."""
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_json_value(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_json_value(a, b) for a, b in zip(left, right))
    return left == right


def note_key(row):
    """Return a known platform/content identity; missing IDs are not a note."""
    note_id = row.get("note_id")
    if not isinstance(note_id, str) or not note_id.strip():
        return None
    return str(row.get("platform", "")), note_id


def pointer_get(document, pointer):
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("invalid JSON Pointer")
    value = document
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise ValueError("invalid JSON Pointer escape")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise ValueError("invalid JSON Pointer array index")
            value = value[int(token)]
        else:
            value = value[token]
    return value


def validate(document, base):
    errors, warnings = [], []
    if not isinstance(document, dict):
        return ["root must be an object"], [], {}
    for field in ("meta", "evidence", "annotations", "findings"):
        expected = dict if field == "meta" else list
        if not isinstance(document.get(field), expected):
            errors.append(f"{field}: expected {expected.__name__}")
    if errors:
        return errors, warnings, {}
    for field in ("run_id", "collection_mode", "coding_version", "analysis_as_of"):
        if not document["meta"].get(field):
            errors.append(f"meta missing {field}")
    if document["meta"].get("collection_mode") not in ("offline", "mcp", "cli", "mixed"):
        errors.append("meta.collection_mode must be offline, mcp, cli or mixed")
    if not valid_iso_time(document["meta"].get("analysis_as_of")):
        errors.append("meta.analysis_as_of must be an ISO timestamp with timezone")
    final_stage = document["meta"].get("stage") == "final"
    theme_ids = set()
    if final_stage:
        rules = document.get("coding_rules")
        if not isinstance(rules, dict) or not rules:
            errors.append("final snapshot needs coding_rules")
            rules = {}
        if rules.get("version") != document["meta"].get("coding_version"):
            errors.append("coding_rules.version differs from meta.coding_version")
        themes = rules.get("themes")
        if not isinstance(themes, list) or not themes:
            errors.append("coding_rules.themes must be a non-empty list")
            themes = []
        for i, theme in enumerate(themes):
            if not isinstance(theme, dict):
                errors.append(f"coding_rules.themes[{i}] must be an object")
                continue
            tid = theme.get("id")
            if not isinstance(tid, str) or not tid.strip():
                errors.append(f"coding_rules.themes[{i}] needs a non-empty id")
            elif tid in theme_ids:
                errors.append(f"duplicate coding theme id: {tid}")
            else:
                theme_ids.add(tid)
            if not isinstance(theme.get("definition"), str) or not theme["definition"].strip():
                errors.append(f"coding_rules.themes[{i}] needs a definition")
            for field in ("include", "exclude"):
                criteria = theme.get(field)
                if not isinstance(criteria, list) or any(not isinstance(x, str) or not x.strip() for x in criteria):
                    errors.append(f"coding_rules.themes[{i}].{field} must be a list of non-empty criteria")
    elif "stage" not in document["meta"]:
        warnings.append("Legacy snapshot has no meta.stage; final coding-rule definitions were not validated.")
    evidence, annotations, findings = {}, {}, {}
    raw_cache = {}
    source_keys = set()
    metric_provenance = {"source_checked": 0, "declared_unavailable": 0, "unverified": 0, "invalid": 0}

    def source_value(ref):
        if not isinstance(ref, dict) or not isinstance(ref.get("file"), str) or "pointer" not in ref:
            raise ValueError("raw reference needs file and pointer")
        if Path(ref["file"]).is_absolute():
            raise ValueError("raw file path must be relative to the run directory")
        path = (base / ref["file"]).resolve()
        path.relative_to(base.resolve())
        if path not in raw_cache:
            raw_cache[path] = json.loads(path.read_text(encoding="utf-8-sig"))
        return pointer_get(raw_cache[path], ref["pointer"])

    for i, row in enumerate(document["evidence"]):
        if not isinstance(row, dict):
            errors.append(f"evidence[{i}] must be an object")
            continue
        eid = row.get("id")
        if not isinstance(eid, str) or not eid:
            errors.append(f"evidence[{i}] missing string id")
            continue
        if eid in evidence:
            errors.append(f"duplicate evidence id: {eid}")
        evidence[eid] = row
        for key in ("platform", "unit_id", "text"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                errors.append(f"{eid}: {key} must be a non-empty string")
        for key in ("note_id", "collected_at"):
            if key not in row:
                errors.append(f"{eid}: missing {key} (null requires a missing_metadata reason)")
            elif row[key] is None:
                missing = row.get("missing_metadata")
                reason = missing.get(key) if isinstance(missing, dict) else None
                if not isinstance(reason, str) or not reason.strip():
                    errors.append(f"{eid}: null {key} requires a non-empty missing_metadata.{key} reason")
            elif not isinstance(row[key], str) or not row[key].strip():
                errors.append(f"{eid}: {key} must be a non-empty string or null")
        if "collected_at" in row and row["collected_at"] is None:
            if not isinstance(row.get("imported_at"), str) or not row["imported_at"].strip():
                errors.append(f"{eid}: null collected_at requires a non-empty imported_at")
        if "url" not in row or (row["url"] is not None and (not isinstance(row["url"], str) or not row["url"].strip())):
            errors.append(f"{eid}: url must be a non-empty string or null when unavailable")
        if "published_at" not in row:
            errors.append(f"{eid}: missing published_at (null allowed)")
        elif row["published_at"] is not None and not valid_iso_time(row["published_at"], allow_date=True):
            errors.append(f"{eid}: published_at must be an ISO date or timestamp with timezone, or null")
        for field in ("collected_at", "imported_at"):
            if field in row and row[field] is not None and not valid_iso_time(row[field]):
                errors.append(f"{eid}: {field} must be an ISO timestamp with timezone")
        for field, allowed in (("unit_type", ("note", "comment", "reply", "transcript")),
                               ("text_kind", ("full_text", "summary", "transcript", "rewritten", "unknown"))):
            if field in row and row[field] not in allowed:
                errors.append(f"{eid}: invalid {field}")
        metrics = row.get("metrics")
        if metrics is not None:
            if not isinstance(metrics, dict):
                errors.append(f"{eid}: metrics must be an object or null")
            else:
                for name, value in metrics.items():
                    if not isinstance(name, str) or not name.strip() or not valid_metric(value):
                        errors.append(f"{eid}: invalid metric {name!r}; use a nonnegative number, null or raw/value object")
        parent = row.get("parent_unit_id")
        if parent is not None and (not isinstance(parent, str) or not parent.strip()):
            errors.append(f"{eid}: parent_unit_id must be a non-empty string or null")
        elif parent is not None:
            if parent == row.get("unit_id"):
                errors.append(f"{eid}: source unit cannot be its own parent")
            if row.get("unit_type") in ("note", "transcript"):
                errors.append(f"{eid}: note/transcript must not have a comment parent")
        key = tuple(str(row.get(k, "")) for k in ("platform", "note_id", "unit_id", "span_id", "text"))
        if key in source_keys:
            errors.append(f"{eid}: duplicate source passage")
        source_keys.add(key)
        ref = row.get("raw_ref")
        if not isinstance(ref, dict) or not isinstance(ref.get("file"), str) or "pointer" not in ref:
            errors.append(f"{eid}: raw_ref needs file and pointer")
            continue
        try:
            original = source_value(ref)
            if not isinstance(original, str) or not isinstance(row.get("text"), str) or row["text"] not in original:
                errors.append(f"{eid}: text is not a continuous passage in raw source")
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            errors.append(f"{eid}: invalid raw reference: {exc}")
        if isinstance(metrics, dict) and metrics:
            raw_fields = row.get("raw_field")
            if raw_fields is None:
                metric_provenance["unverified"] += len(metrics)
                warnings.append(f"{eid}: metrics have no raw_field mapping; source values were not verified, including in final reports.")
            elif not isinstance(raw_fields, dict) or not isinstance(raw_fields.get("metrics"), dict):
                metric_provenance["invalid"] += len(metrics)
                errors.append(f"{eid}: raw_field.metrics must be a field-to-JSON-Pointer mapping")
            else:
                pointers = raw_fields["metrics"]
                for name, metric in metrics.items():
                    context = f"{eid}.metrics.{name}"
                    if not valid_metric(metric) or not isinstance(metric, dict):
                        metric_provenance["invalid"] += 1
                        errors.append(f"{context}: mapped metric must contain valid raw/value fields")
                        continue
                    if name not in pointers:
                        metric_provenance["invalid"] += 1
                        errors.append(f"{context}: missing raw_field.metrics pointer (use null only when unavailable)")
                        continue
                    pointer = pointers[name]
                    if pointer is None:
                        if metric["raw"] is not None or metric["value"] is not None:
                            metric_provenance["invalid"] += 1
                            errors.append(f"{context}: unavailable field cannot have a raw or numeric value")
                        else:
                            metric_provenance["declared_unavailable"] += 1
                        continue
                    try:
                        original_metric = source_value({"file": ref["file"], "pointer": pointer})
                        if not same_json_value(metric["raw"], original_metric):
                            raise ValueError("raw metric differs from its recorded source field")
                        metric_provenance["source_checked"] += 1
                    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                        metric_provenance["invalid"] += 1
                        errors.append(f"{context}: invalid metric source: {exc}")
    parent_units = {}
    for row in evidence.values():
        platform, unit_id = row.get("platform"), row.get("unit_id")
        if isinstance(platform, str) and isinstance(unit_id, str):
            parent_units.setdefault((platform, unit_id), []).append(row)
    for eid, row in evidence.items():
        parent = row.get("parent_unit_id")
        if not isinstance(parent, str) or not parent.strip():
            if row.get("unit_type") == "reply":
                warnings.append(f"{eid}: reply parent is unknown; thread context is incomplete.")
            continue
        platform = row.get("platform")
        candidates = parent_units.get((platform, parent), []) if isinstance(platform, str) else []
        known = note_key(row)
        matching = [p for p in candidates if known is not None and note_key(p) == known]
        if not matching:
            if known is not None and candidates and all(note_key(p) is not None for p in candidates):
                errors.append(f"{eid}: parent_unit_id belongs to a different content item")
            else:
                warnings.append(f"{eid}: parent content is unavailable or unidentified; same-content relationship was not verified.")
            continue
        role = row.get("unit_type")
        allowed_parents = {"comment": ("note",), "reply": ("comment", "reply")}.get(role) if isinstance(role, str) else None
        if allowed_parents and any(p.get("unit_type") is not None and p["unit_type"] not in allowed_parents for p in matching):
            errors.append(f"{eid}: parent unit_type is incompatible with child unit_type")
    for i, row in enumerate(document["annotations"]):
        if not isinstance(row, dict):
            errors.append(f"annotations[{i}] must be an object")
            continue
        eid = row.get("evidence_id")
        if not isinstance(eid, str) or eid not in evidence:
            errors.append(f"annotations[{i}]: unknown evidence id")
            continue
        if eid in annotations:
            errors.append(f"{eid}: multiple current annotations")
        annotations[eid] = row
        if row.get("status") not in ("admitted", "excluded", "uncertain", "pending"):
            errors.append(f"{eid}: invalid annotation status")
        if row.get("assessor") not in ("model", "human", "mixed"):
            errors.append(f"{eid}: invalid assessor")
        if not row.get("reason") or not row.get("coding_version"):
            errors.append(f"{eid}: reason and coding_version required")
        if row.get("coding_version") != document["meta"].get("coding_version"):
            errors.append(f"{eid}: coding version differs from snapshot")
        if row.get("status") == "admitted" and not row.get("primary_theme"):
            errors.append(f"{eid}: admitted evidence needs primary_theme")
        if final_stage and row.get("status") == "admitted":
            theme = row.get("primary_theme")
            if not isinstance(theme, str) or theme not in theme_ids:
                errors.append(f"{eid}: primary_theme is not defined in final coding_rules")

    admitted = {eid for eid, row in annotations.items() if row.get("status") == "admitted"}

    def id_list(row, field, context):
        ids = row.get(field, [])
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
            errors.append(f"{context}.{field}: expected list of ids")
            return set()
        if len(ids) != len(set(ids)):
            errors.append(f"{context}.{field}: duplicate ids")
        if set(ids) - admitted:
            errors.append(f"{context}.{field}: references non-admitted or missing evidence")
        return set(ids) & admitted

    def count_units(ids, unit):
        if unit == "evidence":
            return len(ids)
        return len({key for e in ids if (key := note_key(evidence[e])) is not None})

    finding_stats = []
    for i, row in enumerate(document["findings"]):
        if not isinstance(row, dict):
            errors.append(f"findings[{i}] must be an object")
            continue
        fid = row.get("id")
        if not isinstance(fid, str) or not fid:
            errors.append(f"findings[{i}] needs string id")
            continue
        if fid in findings:
            errors.append(f"duplicate finding id: {fid}")
        findings[fid] = row
        for key in ("claim", "interpretation", "limits", "opportunity", "validation"):
            if not row.get(key):
                errors.append(f"{fid}: missing {key}")
        for key in ("support_ids", "counter_ids"):
            if key not in row:
                errors.append(f"{fid}: missing {key}")
        support = id_list(row, "support_ids", fid)
        counter = id_list(row, "counter_ids", fid)
        if not support:
            errors.append(f"{fid}: no admitted support evidence")
        if support & counter:
            errors.append(f"{fid}: same evidence in support and counter")
        notes = count_units(support, "note")
        for field, actual in (("support_count", len(support)), ("support_note_count", notes)):
            if field in row and row[field] != actual:
                errors.append(f"{fid}.{field}: expected {actual}, got {row[field]}")
        quotes = row.get("quotes", [])
        if not isinstance(quotes, list):
            errors.append(f"{fid}.quotes: expected list")
            quotes = []
        for quote in quotes:
            if not isinstance(quote, dict):
                errors.append(f"{fid}: quote must be an object")
                continue
            eid, text = quote.get("evidence_id"), quote.get("text")
            if not isinstance(eid, str) or eid not in support | counter:
                errors.append(f"{fid}: quote missing, rewritten or outside finding evidence")
                continue
            if evidence[eid].get("text_kind") in ("summary", "rewritten", "unknown"):
                errors.append(f"{fid}: direct quote cannot use {evidence[eid]['text_kind']} evidence {eid}")
            source_text = evidence[eid].get("text")
            if not isinstance(text, str) or not text or not isinstance(source_text, str) or text not in source_text:
                errors.append(f"{fid}: quote missing, rewritten or outside finding evidence")
        stat = {"id": fid, "support_evidence": len(support), "support_notes": notes, "counter_evidence": len(counter)}
        if "proportion" in row:
            p = row["proportion"]
            if not isinstance(p, dict):
                errors.append(f"{fid}.proportion: expected object")
                p = {}
            numerator = id_list(p, "numerator_ids", fid + ".proportion")
            denominator = id_list(p, "denominator_ids", fid + ".proportion")
            unit = p.get("unit")
            if unit not in ("evidence", "note"):
                errors.append(f"{fid}: proportion unit must be evidence or note")
            if not denominator or not numerator <= denominator:
                errors.append(f"{fid}: empty denominator or numerator outside denominator")
            if not p.get("description") or not p.get("window") or not isinstance(p.get("multi_label"), bool):
                errors.append(f"{fid}: proportion needs description, window and boolean multi_label")
            unknown_notes = sorted(e for e in numerator | denominator if note_key(evidence[e]) is None)
            if unit == "note" and unknown_notes:
                errors.append(f"{fid}: note proportion contains evidence without note_id: {', '.join(unknown_notes)}")
            else:
                stat["fraction"] = [count_units(numerator, unit), count_units(denominator, unit)]
        finding_stats.append(stat)
    states = Counter(str(annotations.get(eid, {}).get("status", "pending")) for eid in evidence)
    if states["pending"] or states["uncertain"]:
        warnings.append("Coverage incomplete; do not describe unprocessed items as excluded.")
    if not findings:
        warnings.append("No findings recorded; this snapshot is not a completed analytical report.")
    summary = {
        "evidence": len(evidence),
        "source_units": len({tuple(str(r.get(k, "")) for k in ("platform", "note_id", "unit_id")) for r in evidence.values()}),
        "notes": count_units(evidence, "note"),
        "unknown_note_evidence": sum(note_key(row) is None for row in evidence.values()),
        "metric_provenance": metric_provenance,
        "states": {s: states[s] for s in ("admitted", "excluded", "uncertain", "pending")},
        "admitted_by_platform": dict(Counter(str(evidence[e].get("platform", "")) for e in admitted)),
        "findings": finding_stats,
    }
    return errors, warnings, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.analysis.read_text(encoding="utf-8-sig"))
        errors, warnings, summary = validate(document, args.analysis.resolve().parent)
    except (OSError, ValueError) as exc:
        print(json.dumps({"errors": [str(exc)]}, ensure_ascii=True))
        return 2
    print(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings, "summary": summary}, ensure_ascii=True, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
