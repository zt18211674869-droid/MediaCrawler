"""Snapshot explicit run artifacts and report stale downstream dependencies.

No network or semantic completion declarations. Existing snapshots are not replaced.
Usage: python artifact_manifest.py snapshot RUN --artifact role=path [--depends child=parent]
       python artifact_manifest.py validate RUN [--output result.json]
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_path(run, value):
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
        raise ValueError("artifact path must be relative")
    path = (run / value).resolve()
    if not path.is_relative_to(run) or path == run:
        raise ValueError("artifact path leaves the run directory: " + value)
    return path


def graph_errors(rows):
    errors, visiting, visited = [], set(), set()

    def walk(role):
        if role in visiting:
            errors.append("cyclic artifact dependency at " + role)
            return
        if role in visited:
            return
        visiting.add(role)
        for dependency in rows[role].get("depends_on", []):
            parent = dependency.get("role")
            if parent not in rows:
                errors.append("unknown dependency role: " + str(parent))
            else:
                walk(parent)
        visiting.remove(role)
        visited.add(role)

    for role in rows:
        walk(role)
    return errors


def snapshot(run_dir, artifacts, dependencies=(), output="artifact-manifest.json"):
    run = Path(run_dir).resolve()
    out = local_path(run, output)
    if out.exists():
        raise ValueError("snapshot already exists; use a new output name")
    if not artifacts:
        raise ValueError("select at least one explicit --artifact role=path")
    rows, paths = {}, set()
    for role, name in artifacts:
        if not isinstance(role, str) or not role.strip() or role in rows:
            raise ValueError("artifact roles must be unique nonempty strings")
        path = local_path(run, name)
        if path == out or path.name == "artifact-manifest.json" or role in {"validation", "run_validation"}:
            raise ValueError("do not snapshot the manifest itself or final validation output")
        if path in paths:
            raise ValueError("duplicate artifact file: " + name)
        schema = None
        if path.suffix.lower() == ".json":
            try:
                doc = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(doc, dict):
                    meta = doc.get("meta", {})
                    schema = doc.get("schema_version") or (meta.get("schema_version") if isinstance(meta, dict) else None)
            except (ValueError, UnicodeError):
                raise ValueError("JSON artifact is unreadable: " + name)
        rows[role] = {"role": role, "path": Path(name).as_posix(), "sha256": digest(path),
                      "schema_version": schema, "depends_on": []}
        paths.add(path)
    edges = set()
    for child, parent in dependencies:
        if child not in rows or parent not in rows:
            raise ValueError("dependency roles must be selected artifacts")
        if (child, parent) in edges:
            raise ValueError("duplicate artifact dependency")
        edges.add((child, parent))
        rows[child]["depends_on"].append({"role": parent, "sha256": rows[parent]["sha256"]})
    errors = graph_errors(rows)
    if errors:
        raise ValueError("; ".join(errors))
    doc = {"schema_version": "artifact-manifest-v1", "created_at": datetime.now(timezone.utc).isoformat(),
           "generated_by": {"tool": "artifact_manifest.py", "version": "1"}, "artifacts": list(rows.values())}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    return doc


def validate(run_dir, manifest="artifact-manifest.json"):
    run = Path(run_dir).resolve()
    errors, warnings, changed, affected = [], [], set(), set()
    rows = {}
    try:
        manifest_path = local_path(run, manifest)
        doc = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(doc, dict) or doc.get("schema_version") != "artifact-manifest-v1":
            raise ValueError("unsupported artifact manifest schema")
        values = doc.get("artifacts")
        if not isinstance(values, list) or not values:
            raise ValueError("artifacts must be a nonempty array")
        paths = set()
        for row in values:
            if not isinstance(row, dict) or not isinstance(row.get("role"), str) or not row["role"].strip():
                raise ValueError("artifacts need nonempty roles")
            role = row["role"]
            if role in rows:
                raise ValueError("duplicate artifact role: " + role)
            path = local_path(run, row.get("path"))
            if path == manifest_path or path in paths:
                raise ValueError("manifest self-reference or duplicate artifact file")
            paths.add(path)
            expected = row.get("sha256")
            if not isinstance(expected, str) or len(expected) != 64 or any(x not in "0123456789abcdef" for x in expected):
                raise ValueError("invalid artifact SHA256: " + role)
            deps = row.get("depends_on")
            if not isinstance(deps, list) or any(not isinstance(x, dict) or not isinstance(x.get("role"), str) for x in deps):
                raise ValueError("depends_on must contain role/hash objects: " + role)
            if len({x["role"] for x in deps}) != len(deps):
                raise ValueError("duplicate dependency: " + role)
            rows[role] = row
            if not path.is_file() or digest(path) != expected:
                changed.add(role)
                errors.append("artifact changed or missing: " + role)
        errors.extend(graph_errors(rows))
        for role, row in rows.items():
            for dep in row["depends_on"]:
                parent = rows.get(dep["role"])
                if parent is not None and dep.get("sha256") != parent["sha256"]:
                    changed.add(role)
                    errors.append("dependency snapshot hash mismatch: " + role + " <- " + dep["role"])
        affected = set(changed)
        while True:
            more = {role for role, row in rows.items() if any(x["role"] in affected for x in row["depends_on"])}
            if more <= affected:
                break
            affected.update(more)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
    warnings.append("Declared dependencies track revisions; hashes do not prove semantic validity or complete dependency selection.")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "summary": {"artifacts": len(rows), "changed_artifacts": sorted(changed),
                        "downstream_affected": sorted(affected - changed)}, "stale_artifacts": sorted(affected)}


def pair(text):
    parts = text.split("=", 1)
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError("expected role=path or child=parent")
    return tuple(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["snapshot", "validate"])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--artifact", action="append", type=pair, default=[])
    parser.add_argument("--depends", action="append", type=pair, default=[])
    parser.add_argument("--manifest", default="artifact-manifest.json", help="manifest inside run to validate")
    parser.add_argument("--output", help="snapshot path inside run; validation result path for validate")
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            doc = snapshot(args.run_dir, args.artifact, args.depends, args.output or "artifact-manifest.json")
            result = {"ok": True, "artifacts": len(doc["artifacts"])}
        else:
            result = validate(args.run_dir, args.manifest)
            if args.output:
                out = Path(args.output)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, TypeError) as exc:
        result = {"ok": False, "errors": [str(exc)], "warnings": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
