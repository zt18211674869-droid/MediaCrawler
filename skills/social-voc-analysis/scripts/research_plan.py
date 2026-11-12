"""Read and check research plans without rewriting historical files. Standard library only."""
import argparse
import copy
import json
from pathlib import Path


def text(value):
    return isinstance(value, str) and bool(value.strip())


def local_path(root, value):
    if not text(value) or Path(value).is_absolute():
        raise ValueError("expected a relative file path inside run_dir")
    target = (Path(root).resolve() / value).resolve()
    if not target.is_relative_to(Path(root).resolve()):
        raise ValueError("file path leaves run_dir")
    return target


def normalize(document):
    """Return a copy with canonical keys; never infer answers or completion."""
    if not isinstance(document, dict):
        raise ValueError("research-spec must be an object")
    plan = copy.deepcopy(document)
    rows = plan.get("question_plan", plan.get("questions", []))
    if isinstance(rows, list):
        questions = []
        for row in rows:
            if not isinstance(row, dict):
                questions.append(row)
                continue
            item = dict(row)
            for key, aliases in {
                "evidence_needed": ("evidence",),
                "method": ("analysis_method",),
                "completion_criteria": ("completion_criterion", "completion"),
            }.items():
                if key not in item:
                    for alias in aliases:
                        if alias in item:
                            item[key] = item[alias]
                            break
            questions.append(item)
        plan["question_plan"] = questions
    else:
        plan["question_plan"] = rows
    plan.setdefault("module_plan", [])
    plan.setdefault("quantitative_plan", {})
    plan.setdefault("question_coverage", [])
    outputs = plan.get("outputs", [])
    if isinstance(outputs, list):
        defaults = {"html": "report.html", "pdf": "report.pdf", "csv": "evidence.csv"}
        outputs = [({"format": x.lower(), "path": defaults[x.lower()]} if isinstance(x, str) and x.lower() in defaults else x) for x in outputs]
    plan["outputs"] = outputs
    return plan


def load(path):
    return normalize(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def validate(value, strict=False):
    errors, warnings = [], []
    try:
        plan = load(value) if isinstance(value, (str, Path)) else normalize(value)
    except (OSError, ValueError, TypeError) as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": [], "plan": {}}
    version = plan.get("schema_version")
    modern = version == "research-spec-v1"
    if version is not None and not modern:
        errors.append("unsupported research-spec schema_version")
    if not modern:
        warnings.append("Historical plan normalized in memory; original file was not changed.")
        if strict:
            errors.append("delivery/revision requires an explicit research-spec-v1 plan")
    if modern:
        if plan.get("collection_mode") not in ("offline", "mcp"):
            errors.append("new research collection_mode must be offline or mcp")
        if plan.get("external_access") != {"provider": "guaikei", "transport": "mcp"}:
            errors.append("external_access must allow guaikei MCP only")
    rows = plan.get("question_plan")
    ids = set()
    if not isinstance(rows, list) or not rows:
        errors.append("question_plan must contain explicit question IDs")
        rows = []
    for index, row in enumerate(rows):
        label = f"question_plan[{index}]"
        if not isinstance(row, dict) or not text(row.get("id")):
            errors.append(label + " requires a nonempty id")
            continue
        if row["id"] in ids:
            errors.append(label + " duplicate question ID: " + row["id"])
        ids.add(row["id"])
        fields = ("question", "evidence_needed", "method", "completion_criteria") if modern else ("question",)
        for field in fields:
            val = row.get(field)
            if not (text(val) or (field == "completion_criteria" and isinstance(val, list) and val and all(text(x) for x in val))):
                errors.append(label + " requires " + field)

    def refs(values, label):
        if not isinstance(values, list) or any(not text(x) for x in values):
            errors.append(label + " must be a string array")
            return set()
        if len(set(values)) != len(values):
            errors.append(label + " contains duplicate IDs")
        unknown = set(values) - ids
        if unknown:
            errors.append(label + " references unknown questions: " + ", ".join(sorted(unknown)))
        return set(values)

    modules = plan.get("module_plan")
    if not isinstance(modules, list):
        errors.append("module_plan must be an array")
    else:
        seen = set()
        for index, row in enumerate(modules):
            label = f"module_plan[{index}]"
            if not isinstance(row, dict) or not text(row.get("module")):
                errors.append(label + " requires module")
                continue
            if row["module"] in seen:
                errors.append(label + " duplicate module")
            seen.add(row["module"])
            if type(row.get("selected")) is not bool:
                errors.append(label + " selected must be boolean")
            linked = refs(row.get("question_ids", []), label + ".question_ids")
            if row.get("selected") and not linked:
                errors.append(label + " selected module must link research questions")
            artifacts = row.get("required_artifacts", [])
            if not isinstance(artifacts, list):
                errors.append(label + ".required_artifacts must be an array")
                artifacts = []
            for filename in artifacts:
                try:
                    local_path(Path.cwd(), filename)
                except (TypeError, ValueError) as exc:
                    errors.append(label + ".required_artifacts: " + str(exc))
    quantitative = plan.get("quantitative_plan")
    if not isinstance(quantitative, dict):
        errors.append("quantitative_plan must be an object")
        quantitative = {}
    mode = quantitative.get("mode")
    if mode not in (None, "case_exploration", "sample_distribution") or modern and mode is None:
        errors.append("invalid quantitative_plan.mode")
    for name in ("keyword_plan", "journey_plan"):
        if name in plan and not isinstance(plan[name], dict):
            errors.append(name + " must be an object")
    required = quantitative.get("required_tables", [])
    if not isinstance(required, list):
        errors.append("quantitative_plan.required_tables must be an array")
        required = []
    if modern and mode == "sample_distribution" and not required:
        errors.append("sample_distribution must declare required_tables in research-spec")
    table_ids = set()
    for row in required:
        if not isinstance(row, dict) or not text(row.get("id")) or not text(row.get("axis_id")):
            errors.append("required table needs id and axis_id")
            continue
        if row["id"] in table_ids:
            errors.append("duplicate required table ID: " + row["id"])
        table_ids.add(row["id"])
        if not refs(row.get("question_ids"), row["id"] + ".question_ids"):
            errors.append(row["id"] + " must link research questions")
    outputs = plan.get("outputs")
    if not isinstance(outputs, list):
        errors.append("outputs must be an array")
    else:
        for row in outputs:
            if not isinstance(row, dict):
                (errors if modern else warnings).append("output must declare path and format")
                continue
            try:
                local_path(Path.cwd(), row.get("path"))
            except (TypeError, ValueError) as exc:
                errors.append("output path: " + str(exc))
            if not text(row.get("format")):
                errors.append("output requires format")
    coverage = plan.get("question_coverage")
    if not isinstance(coverage, list):
        errors.append("question_coverage must be an array")
    else:
        seen = set()
        for row in coverage:
            if not isinstance(row, dict) or not text(row.get("question_id")) or row["question_id"] not in ids:
                errors.append("question_coverage references unknown question")
                continue
            qid = row["question_id"]
            if qid in seen:
                errors.append("duplicate question_coverage: " + qid)
            seen.add(qid)
            if row.get("status") not in ("answered", "partial", "unknown"):
                errors.append(qid + " invalid answer status")
            if row.get("status") in ("partial", "unknown") and not (text(row.get("gaps")) or isinstance(row.get("gaps"), list) and row["gaps"] and all(text(x) for x in row["gaps"])):
                errors.append(qid + " partial/unknown answer needs explicit gaps")
            for key in ("finding_ids", "table_ids"):
                values = row.get(key, [])
                if not isinstance(values, list) or any(not text(x) for x in values):
                    errors.append(qid + "." + key + " must be a string array")
        if strict and seen != ids:
            errors.append("question_coverage must record an answer or explicit gap for every question")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "plan": plan}


def check_quantitative_plan(plan, spec):
    """Check cross-file identity and obligations, not statistical classification meaning."""
    errors = []
    if not isinstance(plan, dict) or not isinstance(spec, dict):
        return ["research and quantitative plans must be objects"]
    for key in ("questions", "required_tables"):
        if not isinstance(spec.get(key), list):
            errors.append("quantitative-spec." + key + " must be an array")
    if errors:
        return errors
    question_ids = {r["id"] for r in plan.get("question_plan", []) if isinstance(r, dict) and text(r.get("id"))}
    spec_ids = {r["id"] for r in spec.get("questions", []) if isinstance(r, dict) and text(r.get("id"))}
    if not spec_ids <= question_ids:
        errors.append("quantitative-spec contains questions absent from research-spec")
    quantitative = plan.get("quantitative_plan", {})
    if quantitative.get("mode") is not None and quantitative["mode"] != spec.get("mode"):
        errors.append("quantitative mode differs from research-spec")
    actual = {r["id"]: r for r in spec.get("required_tables", []) if isinstance(r, dict) and text(r.get("id"))}
    planned = quantitative.get("required_tables", [])
    if isinstance(planned, list):
        for row in planned:
            if not isinstance(row, dict) or not text(row.get("id")):
                continue
            other = actual.get(row["id"])
            other_refs = other.get("question_ids") if isinstance(other, dict) else None
            refs = row.get("question_ids")
            if not isinstance(other_refs, list) or any(not text(x) for x in other_refs) or not isinstance(refs, list) or any(not text(x) for x in refs):
                errors.append(row["id"] + ": quantitative table needs question_ids arrays")
            elif other.get("axis_id") != row.get("axis_id") or set(other_refs) != set(refs):
                errors.append(row["id"] + ": quantitative table differs from research-spec obligation")
    count = quantitative.get("required_table_count")
    if count is not None and (type(count) is not int or count != len(actual)):
        errors.append("required_table_count differs from quantitative-spec")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = validate(args.plan, args.strict)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
