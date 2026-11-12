"""Normalize a saved guaikei MCP response using an explicitly reviewed mapping.

No network, field guessing, coding, or completion claims. Existing runs are never
overwritten. Usage: normalize_mcp.py RESPONSE MAPPING RUN_DIR
"""
import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path

from prepare_analysis import prepare
from validate_analysis import pointer_get


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(data):
    def reject(value):
        raise ValueError("non-finite JSON number: " + value)
    return json.loads(data, parse_constant=reject)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def identifier(value, label):
    if type(value) is int:
        return str(value)
    if not text(value):
        raise ValueError(label + " must be a nonempty string or exact JSON integer; floats are rejected")
    return value


def join_pointer(base, token):
    return base + "/" + str(token).replace("~", "~0").replace("/", "~1")


def resolve_field(record, rule, label):
    if not isinstance(rule, dict) or (("pointer" in rule) == ("literal" in rule)):
        raise ValueError(label + " needs exactly one pointer or literal")
    if "literal" in rule:
        return rule["literal"]
    try:
        return pointer_get(record, rule["pointer"])
    except (KeyError, IndexError):
        if rule.get("optional") is True:
            return None
        raise ValueError(label + ": source pointer does not exist") from None


def normalize(response_path, mapping_path, run_dir):
    response_path, mapping_path = Path(response_path), Path(mapping_path)
    run = Path(run_dir).absolute()
    if run.is_symlink() or (run.exists() and (not run.is_dir() or any(run.iterdir()))):
        raise ValueError("RUN_DIR must be absent or an empty, non-symlink directory")
    raw = response_path.read_bytes()
    mapping_bytes = mapping_path.read_bytes()
    response, mapping = read_json(raw.decode("utf-8-sig")), read_json(mapping_bytes.decode("utf-8-sig"))
    if isinstance(response, dict) and response.get("isError") is True:
        raise ValueError("MCP reported isError=true; keep the response as a failed task, not analysis input")
    if not isinstance(mapping, dict) or mapping.get("schema_version") != "mcp-mapping-v1" or mapping.get("provider") != "guaikei":
        raise ValueError("mapping needs schema_version=mcp-mapping-v1 and provider=guaikei")
    for field in ("run_id", "mapping_version", "mapping_basis", "collected_at"):
        if not text(mapping.get(field)):
            raise ValueError("mapping needs " + field)
    payload_rule = mapping.get("payload")
    if not isinstance(payload_rule, dict) or not isinstance(payload_rule.get("pointer"), str) or type(payload_rule.get("decode_json")) is not bool:
        raise ValueError("payload needs explicit pointer and boolean decode_json")
    try:
        payload = pointer_get(response, payload_rule["pointer"])
        if payload_rule["decode_json"]:
            if not isinstance(payload, str):
                raise ValueError("decode_json payload must be a JSON string")
            payload = read_json(payload)
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("unsupported MCP payload pointer or shape: " + str(exc)) from None
    records_pointer = mapping.get("records_pointer")
    if not isinstance(records_pointer, str):
        raise ValueError("records_pointer must explicitly identify a record array")
    records = pointer_get(payload, records_pointer)
    if not isinstance(records, list):
        raise ValueError("records_pointer does not identify an array; no shape guessing is performed")
    fields = mapping.get("fields")
    required = {"platform", "content_id", "unit_id", "unit_type", "text_kind", "text", "url", "published_at"}
    allowed = required | {"title", "author_id", "author_name", "parent_unit_id", "collected_at", "missing_metadata", "imported_at"}
    if not isinstance(fields, dict) or not required <= fields.keys() or not fields.keys() <= allowed:
        raise ValueError("fields needs the documented required fields and no unknown fields")
    if "pointer" not in fields["text"]:
        raise ValueError("text must point to original source text, not a literal")
    metric_rules = mapping.get("metrics", {})
    if not isinstance(metric_rules, dict):
        raise ValueError("metrics must be an object")
    excluded = mapping.get("excluded_records", [])
    if not isinstance(excluded, list):
        raise ValueError("excluded_records must be an array")
    exclusions = {}
    for entry in excluded:
        if not isinstance(entry, dict) or type(entry.get("index")) is not int or not 0 <= entry["index"] < len(records) or not text(entry.get("reason")) or entry["index"] in exclusions:
            raise ValueError("each exclusion needs a unique, in-range index and specific reason")
        exclusions[entry["index"]] = entry["reason"]
    decoded = payload_rule["decode_json"]
    source_file = "raw/decoded-payload.json" if decoded else "raw/mcp-response.json"
    prefix = "" if decoded else payload_rule["pointer"]
    items, inventory, identities = [], [], {}
    for index, record in enumerate(records):
        record_pointer = join_pointer(prefix + records_pointer, index)
        entry = {"record_index": index, "raw_ref": {"file": source_file, "pointer": record_pointer}}
        if index in exclusions:
            entry.update(disposition="excluded", reason=exclusions[index])
            inventory.append(entry)
            continue
        if not isinstance(record, dict):
            raise ValueError("record " + str(index) + " must be an object or explicitly excluded")
        item = {name: resolve_field(record, rule, "record " + str(index) + "." + name) for name, rule in fields.items()}
        for name in ("platform", "content_id", "unit_id"):
            item[name] = identifier(item[name], name)
        for name in ("author_id", "parent_unit_id"):
            if item.get(name) is not None:
                item[name] = identifier(item[name], name)
        item.setdefault("collected_at", mapping["collected_at"])
        item["raw_ref"] = {"file": source_file, "pointer": record_pointer + fields["text"]["pointer"]}
        item["record_ref"] = entry["raw_ref"]
        item["profile"] = mapping["mapping_version"]
        item["provenance_layer"] = "mcp_tool_output"
        item["content_sha256"] = sha(item["text"].encode("utf-8")) if isinstance(item["text"], str) else None
        if metric_rules:
            item["metrics"], item["raw_field"] = {}, {"metrics": {}}
        for name, rule in metric_rules.items():
            if not text(name) or not isinstance(rule, dict) or "pointer" not in rule or "literal" in rule:
                raise ValueError("metrics require named original-field pointers")
            value = resolve_field(record, rule, "metric " + name)
            number = value if (type(value) is int and value >= 0) or (type(value) is float and value >= 0 and math.isfinite(value)) else None
            if isinstance(value, str) and value.isdecimal():
                number = int(value)
            metric = {"raw": value, "value": number}
            if "unit" in rule:
                metric["unit"] = rule["unit"]
            item["metrics"][name] = metric
            item["raw_field"]["metrics"][name] = record_pointer + rule["pointer"] if value is not None else None
        entry.update(source_identity=[item[k] for k in ("platform", "content_id", "unit_id")])
        if item["text"] is None or (isinstance(item["text"], str) and not item["text"].strip()):
            entry.update(disposition="missing_text", reason="Mapped text is null, empty or whitespace; not read or quoted.")
        elif not isinstance(item["text"], str):
            raise ValueError("mapped text must be string or null")
        else:
            identity = tuple(entry["source_identity"])
            snapshot = {k: v for k, v in item.items() if k not in {"raw_ref", "record_ref", "raw_field"}}
            if identity in identities:
                prior_index, prior = identities[identity]
                if snapshot != prior:
                    raise ValueError("conflicting source snapshots; select explicitly before importing: " + repr(identity))
                entry.update(disposition="duplicate", retained_record_index=prior_index)
            else:
                identities[identity] = index, snapshot
                entry.update(disposition="selected", item_line=len(items) + 1)
                items.append(item)
        inventory.append(entry)
    manifest = {"schema_version": "mcp-collection-v1", "run_id": mapping["run_id"], "collection_mode": "mcp",
                "provider": "guaikei", "provenance_layer": "mcp_tool_output", "research_question": mapping.get("research_question"),
                "mapping_version": mapping["mapping_version"], "mapping_basis": mapping["mapping_basis"],
                "collected_at": mapping["collected_at"], "raw_file": "raw/mcp-response.json", "raw_sha256": sha(raw),
                "mapping_sha256": sha(mapping_bytes), "coverage": {"raw_records": len(records), "selected_records": len(items),
                **{kind: sum(row["disposition"] == kind for row in inventory) for kind in ("missing_text", "duplicate", "excluded")}},
                "derivation": {"payload_pointer": payload_rule["pointer"], "decoded_json": decoded, "record_file": source_file,
                               "records_pointer": prefix + records_pointer},
                "limits": ["MCP tool output, not a complete upstream HTTP journal.", "Mapping meaning and source authenticity require review."]}
    run.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mcp-normalize-", dir=run.parent) as temporary:
        staging = Path(temporary)
        (staging / "raw").mkdir()
        (staging / "raw/mcp-response.json").write_bytes(raw)
        (staging / "mapping.json").write_bytes(mapping_bytes)
        if decoded:
            decoded_bytes = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
            (staging / source_file).write_bytes(decoded_bytes)
            manifest["derivation"]["decoded_sha256"] = sha(decoded_bytes)
        for name, value in (("manifest.json", manifest), ("raw-inventory.json", {"schema_version": "mcp-inventory-v1", "raw_sha256": sha(raw), "records": inventory})):
            (staging / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "items.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n" for item in items), encoding="utf-8")
        prepare(staging)  # validates source pointers and metadata, without writing analysis or assigning labels
        run.mkdir(exist_ok=True)
        if any(run.iterdir()):
            raise ValueError("RUN_DIR changed while preparing; no files were overwritten")
        for path in sorted(staging.rglob("*")):
            target = run / path.relative_to(staging)
            if path.is_dir():
                target.mkdir()
            else:
                with target.open("xb") as stream:
                    stream.write(path.read_bytes())
    return {"ok": True, "run_dir": str(run), "coverage": manifest["coverage"], "coding_performed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("response", type=Path)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        result = normalize(args.response, args.mapping, args.run_dir)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        result = {"ok": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
