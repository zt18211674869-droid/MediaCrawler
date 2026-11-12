"""Recompute planned sample-distribution tables from frozen classification members.

Usage: python validate_quantitative.py RUN_DIR [--output validation.json]
Checks required tables, source bindings, eligibility, complete assignment records,
multi-label rules and n/N/percent. Does not validate semantic coding or sampling
representativeness, and does not replace analysis/opinion/coverage validators.
"""
import argparse
import hashlib
import json
from pathlib import Path

import research_plan


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate(run_dir):
    run = Path(run_dir).resolve()
    errors, warnings = [], []
    summary = {"required_tables": 0, "validated_tables": 0, "axes": 0, "assignments": 0}

    def finish():
        return {"ok": not errors, "errors": errors, "warnings": warnings,
                "summary": summary, "semantic_accuracy_verified": False,
                "sampling_representativeness_verified": False}

    def load(name):
        value = json.loads((run / name).read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError(name + " must be an object")
        return value

    def index(rows, label, key="id"):
        result = {}
        if not isinstance(rows, list):
            errors.append(label + " must be an array")
            return result
        for row in rows:
            if not isinstance(row, dict) or not nonempty(row.get(key)):
                errors.append(label + " needs object rows with nonempty " + key)
                continue
            if row[key] in result:
                errors.append(label + " duplicate ID: " + row[key])
            result[row[key]] = row
        return result

    def ids(value, label):
        if not isinstance(value, list) or any(not nonempty(x) for x in value):
            errors.append(label + " must be a string array")
            return set()
        if len(value) != len(set(value)):
            errors.append(label + " contains duplicate IDs")
        return set(value)

    try:
        spec = load("quantitative-spec.json")
        if spec.get("schema_version") != "quantitative-spec-v1":
            errors.append("unsupported quantitative spec schema")
        if spec.get("mode") not in ("case_exploration", "sample_distribution"):
            errors.append("mode must explicitly be case_exploration or sample_distribution")
        questions = index(spec.get("questions"), "questions")
        required = index(spec.get("required_tables"), "required_tables")
        summary["required_tables"] = len(required)
        plan_path = run / "research-spec.json"
        if plan_path.exists():
            checked_plan = research_plan.validate(plan_path)
            errors.extend("research-spec: " + x for x in checked_plan["errors"])
            warnings.extend(checked_plan["warnings"])
            if checked_plan["ok"]:
                errors.extend(research_plan.check_quantitative_plan(checked_plan["plan"], spec))
        else:
            warnings.append("No research-spec.json; quantitative obligations were checked only within quantitative-spec.")
        if spec.get("mode") == "sample_distribution" and not required:
            errors.append("sample_distribution requires at least one planned table")
        if spec.get("mode") == "case_exploration" and not required:
            warnings.append("Case exploration: no distribution tables planned; no statistical completion claim.")
            return finish()
        coding = load("quantitative-coding.json")
        facts = load("quantitative-facts.json")
        analysis = load("analysis.json")
        opinions = load("opinions.json")
    except (OSError, ValueError, TypeError) as exc:
        errors.append(str(exc))
        return finish()
    if coding.get("schema_version") != "quantitative-coding-v1":
        errors.append("unsupported quantitative coding schema")
    if facts.get("schema_version") != "quantitative-facts-v1":
        errors.append("unsupported quantitative facts schema")
    if coding.get("source_analysis_sha256") != sha(run / "analysis.json"):
        errors.append("coding does not bind current analysis.json")
    if coding.get("source_opinions_sha256") != sha(run / "opinions.json"):
        errors.append("coding does not bind current opinions.json")
    if facts.get("source_coding_sha256") != sha(run / "quantitative-coding.json"):
        errors.append("facts do not bind current quantitative-coding.json")
    opinion_meta = opinions.get("meta")
    if not isinstance(opinion_meta, dict):
        errors.append("opinions.meta must be an object")
        opinion_meta = {}
    if opinion_meta.get("source_sha256") != sha(run / "analysis.json"):
        errors.append("opinions do not bind current analysis.json")
    evidence = index(analysis.get("evidence"), "evidence")
    annotations = index(analysis.get("annotations"), "annotations", "evidence_id")
    opinion_rows = index(opinions.get("opinions"), "opinions")
    axes = index(coding.get("axes"), "axes")
    tables = index(facts.get("tables"), "tables")
    summary["axes"] = len(axes)
    assignments = {}
    rows = coding.get("assignments")
    if not isinstance(rows, list):
        errors.append("assignments must be an array")
        rows = []
    for row in rows:
        if not isinstance(row, dict) or not nonempty(row.get("axis_id")) or not nonempty(row.get("entity_id")):
            errors.append("assignment needs axis_id and entity_id")
            continue
        key = (row["axis_id"], row["entity_id"])
        if key in assignments:
            errors.append("duplicate assignment: " + repr(key))
        assignments[key] = ids(row.get("category_ids"), repr(key) + ".category_ids")
        if row["axis_id"] not in axes:
            errors.append("assignment references unknown axis: " + row["axis_id"])
    summary["assignments"] = len(assignments)
    axis_data = {}
    for aid, axis in axes.items():
        unit = axis.get("unit")
        pool = opinion_rows if unit == "opinion" else evidence
        if unit not in ("source", "opinion"):
            errors.append(aid + ": unit must be source or opinion")
        if type(axis.get("multi_label")) is not bool:
            errors.append(aid + ": multi_label must be boolean")
        for field in ("title", "eligibility", "window"):
            if not nonempty(axis.get(field)):
                errors.append(aid + ": missing " + field)
        scope = ids(axis.get("scope_ids"), aid + ".scope_ids")
        categories = index(axis.get("categories"), aid + ".categories")
        for cid, category in categories.items():
            if not nonempty(category.get("label")):
                errors.append(aid + ": category lacks label: " + cid)
        unknown = axis.get("unknown_category_id")
        if unknown is not None and not nonempty(unknown):
            errors.append(aid + ": unknown category must be nonempty text or null")
            unknown = None
        if unknown is not None and unknown not in categories:
            errors.append(aid + ": unknown category not in codebook")
        actual = {entity for (axis_id, entity) in assignments if axis_id == aid}
        if actual != scope:
            errors.append(aid + ": assignments do not cover scope exactly")
        identities = set()
        for entity in scope:
            if entity not in pool:
                errors.append(aid + ": unknown entity " + entity)
                continue
            eid = pool[entity].get("evidence_id") if unit == "opinion" else entity
            if eid not in evidence or annotations.get(eid, {}).get("status") != "admitted":
                errors.append(aid + ": scope uses a source not admitted: " + entity)
            if unit == "source":
                e = evidence[entity]
                identity = (e.get("platform"), e.get("note_id"), e.get("unit_id"))
                if identity in identities:
                    errors.append(aid + ": duplicate source identity in denominator")
                identities.add(identity)
            member = assignments.get((aid, entity), set())
            if not member <= set(categories):
                errors.append(aid + ": assignment uses unknown category: " + entity)
            if axis.get("multi_label") is False and len(member) != 1:
                errors.append(aid + ": exclusive classification must assign exactly one category: " + entity)
            if unknown is not None and not member:
                errors.append(aid + ": unclassified entity must use explicit unknown category: " + entity)
            if unknown in member and len(member) != 1:
                errors.append(aid + ": unknown cannot overlap substantive categories: " + entity)
        axis_data[aid] = (scope, categories)
    for tid, planned in required.items():
        aid = planned.get("axis_id")
        if not nonempty(aid) or aid not in axes:
            errors.append(tid + ": planned axis missing")
        question_ids = ids(planned.get("question_ids"), tid + ".question_ids")
        if not question_ids or not question_ids <= set(questions):
            errors.append(tid + ": missing or unknown research question")
        if tid not in tables:
            errors.append(tid + ": required table missing")
        elif tables[tid].get("axis_id") != aid:
            errors.append(tid + ": table does not use planned axis")
    for tid, table in tables.items():
        before = len(errors)
        aid = table.get("axis_id")
        if not nonempty(aid) or aid not in axes:
            errors.append(tid + ": table axis missing")
            continue
        axis = axes[aid]
        scope, categories = axis_data[aid]
        if table.get("unit") != axis.get("unit") or table.get("multi_label") != axis.get("multi_label"):
            errors.append(tid + ": table unit or multi_label differs from axis")
        table_rows = index(table.get("rows"), tid + ".rows", "category_id")
        if set(table_rows) != set(categories):
            errors.append(tid + ": rows must include every declared category exactly once")
        for cid, row in table_rows.items():
            if cid not in categories:
                continue
            if any(field not in row for field in ("label", "numerator_ids", "denominator_ids", "n", "N", "percent")):
                errors.append(tid + "/" + cid + ": missing required statistical field")
            expected = {entity for entity in scope if cid in assignments.get((aid, entity), set())}
            numerator = ids(row.get("numerator_ids"), tid + "/" + cid + ".numerator_ids")
            denominator = ids(row.get("denominator_ids"), tid + "/" + cid + ".denominator_ids")
            if numerator != expected or denominator != scope:
                errors.append(tid + "/" + cid + ": members differ from frozen assignments or scope")
            n, N = len(expected), len(scope)
            if type(row.get("n")) is not int or row["n"] != n or type(row.get("N")) is not int or row["N"] != N:
                errors.append(tid + "/" + cid + ": n/N does not match recomputation")
            value = row.get("percent")
            expected_percent = round(100 * n / N, 1) if N else None
            if N == 0:
                if value is not None:
                    errors.append(tid + "/" + cid + ": zero denominator requires null percent")
            elif type(value) not in {int, float} or value != expected_percent:
                errors.append(tid + "/" + cid + ": percent differs from n/N rounded to one decimal")
            if row.get("label") != categories[cid].get("label"):
                errors.append(tid + "/" + cid + ": category label differs from codebook")
            if "discussion_pages" in row:
                eids = {opinion_rows[i].get("evidence_id") for i in expected if i in opinion_rows} if axis["unit"] == "opinion" else expected
                pages = {(evidence[i].get("platform"), evidence[i].get("note_id")) for i in eids if i in evidence and evidence[i].get("note_id")}
                if type(row["discussion_pages"]) is not int or row["discussion_pages"] != len(pages):
                    errors.append(tid + "/" + cid + ": discussion_pages differs from known works")
        if len(errors) == before:
            summary["validated_tables"] += 1
    warnings.append("Classification meaning, denominator eligibility choices and report wording require semantic review.")
    warnings.append("Run analysis, opinion and coverage validators separately; table arithmetic does not prove full-text review.")
    return finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.run_dir)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
