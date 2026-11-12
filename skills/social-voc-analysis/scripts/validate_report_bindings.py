"""Check static HTML bindings against frozen facts, findings and original quotes.

Standard library only; no network, JavaScript execution or visual acceptance.
Usage: python validate_report_bindings.py RUN_DIR [--output result.json]
"""
import argparse
import hashlib
import json
import math
from html.parser import HTMLParser
from pathlib import Path

from validate_analysis import pointer_get


def local_path(run, value):
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
        raise ValueError("expected a relative file path")
    path = (run / value).resolve()
    if not path.is_relative_to(run) or path == run:
        raise ValueError("file path leaves the run directory: " + value)
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(text):
    return " ".join(text.split())


class Bindings(HTMLParser):
    """Capture element text, including child text, without trusting data values."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.rows = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        ignored = tag in {"script", "style", "template", "head"} or any(x[1] for x in self.stack)
        rows = []
        for kind in ("metric", "finding", "quote"):
            attr = "data-" + kind + "-id"
            if attr in attrs:
                row = {"kind": kind, "id": attrs[attr], "text": "", "ignored": ignored}
                self.rows.append(row)
                rows.append(row)
        if tag not in self.VOID:
            self.stack.append((tag, ignored, rows))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if any(x[1] for x in self.stack):
            return
        for _, _, rows in self.stack:
            for row in rows:
                row["text"] += data


def validate(run_dir):
    run = Path(run_dir).resolve()
    errors, warnings = [], []
    summary = {"reports": 0, "metric_elements": 0, "finding_elements": 0, "quote_elements": 0}
    cache, checked = {}, set()

    def finish():
        return {"ok": not errors, "errors": errors, "warnings": warnings, "summary": summary,
                "visual_qa_verified": False, "semantic_accuracy_verified": False}

    try:
        manifest_path = local_path(run, "report-bindings.json")
        doc = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(doc, dict) or doc.get("schema_version") != "report-bindings-v1":
            raise ValueError("unsupported report bindings schema")
        hashes = doc.get("source_hashes")
        reports = doc.get("reports")
        if not isinstance(hashes, dict) or not hashes:
            raise ValueError("source_hashes must bind the frozen source files")
        if not isinstance(reports, list) or not reports:
            raise ValueError("reports must be a nonempty array")
        for name, expected in hashes.items():
            path = local_path(run, name)
            if path == manifest_path:
                raise ValueError("report bindings cannot use themselves as a source")
            if not isinstance(expected, str) or len(expected) != 64 or digest(path) != expected:
                errors.append("source hash mismatch: " + name)

        def source(name):
            path = local_path(run, name)
            if name not in hashes or path == manifest_path:
                raise ValueError("unbound frozen source: " + name)
            if name not in cache:
                cache[name] = json.loads(path.read_text(encoding="utf-8-sig"))
            return cache[name]

        def index(rows, label):
            if not isinstance(rows, list):
                raise ValueError(label + " must be an array")
            values = {}
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
                    raise ValueError(label + " rows need nonempty IDs")
                if row["id"] in values:
                    raise ValueError(label + " has duplicate ID: " + row["id"])
                values[row["id"]] = row
            return values

        for report in reports:
            try:
                if not isinstance(report, dict):
                    raise ValueError("report entry must be an object")
                name = report.get("path")
                path = local_path(run, name)
                if path.suffix.lower() not in {".html", ".htm"}:
                    raise ValueError("static bindings currently require HTML: " + str(name))
                if name in checked:
                    raise ValueError("duplicate report path: " + name)
                checked.add(name)
                parser = Bindings()
                parser.feed(path.read_text(encoding="utf-8-sig"))
                pools = {kind: index(report.get(key, []), key) for kind, key in
                         [("metric", "metrics"), ("finding", "findings"), ("quote", "quotes")]}
                seen = {kind: set() for kind in pools}
                for row in parser.rows:
                    kind, rid = row["kind"], row["id"]
                    summary[kind + "_elements"] += 1
                    if not isinstance(rid, str) or rid not in pools[kind]:
                        errors.append(str(name) + ": unknown " + kind + " ID: " + str(rid))
                        continue
                    seen[kind].add(rid)
                    binding = pools[kind][rid]
                    label = str(name) + "/" + kind + "/" + rid
                    try:
                        if row["ignored"] or not row["text"].strip():
                            raise ValueError("binding has no static report text")
                        if kind == "metric":
                            ref = binding.get("source")
                            if not isinstance(ref, dict) or not isinstance(ref.get("file"), str):
                                raise ValueError("metric needs a frozen facts file and JSON Pointer")
                            if Path(ref["file"]).name not in {"facts.json", "quantitative-facts.json"}:
                                raise ValueError("metric source must be facts.json or quantitative-facts.json")
                            value = pointer_get(source(ref["file"]), ref.get("pointer"))
                            fmt = binding.get("format")
                            if fmt == "text":
                                if not isinstance(value, str):
                                    raise ValueError("text binding needs a string fact")
                                expected = value
                            elif fmt in {"number", "percent"}:
                                if type(value) not in {int, float} or not math.isfinite(value):
                                    raise ValueError("numeric binding needs a finite numeric fact")
                                decimals = binding.get("decimals")
                                if decimals is None:
                                    expected = str(value)
                                elif type(decimals) is int and 0 <= decimals <= 10:
                                    expected = format(value, "." + str(decimals) + "f")
                                else:
                                    raise ValueError("decimals must be an integer from 0 to 10")
                                if fmt == "percent":
                                    expected += "%"
                            else:
                                raise ValueError("unsupported metric display format")
                            if normalized(row["text"]) != normalized(expected):
                                raise ValueError("displayed text differs from frozen fact: " + repr(expected))
                        elif kind == "finding":
                            layer = binding.get("source")
                            if layer not in {"analysis", "opinions"}:
                                raise ValueError("finding source must explicitly be analysis or opinions")
                            source_name = binding.get("source_file", layer + ".json")
                            findings = index(source(source_name).get("findings"), source_name + ".findings")
                            if rid not in findings:
                                raise ValueError("finding does not exist in the specified layer")
                        else:
                            text = binding.get("text")
                            source_name = binding.get("source_file", "analysis.json")
                            evidence = index(source(source_name).get("evidence"), source_name + ".evidence")
                            eid = binding.get("evidence_id")
                            if not isinstance(text, str) or not text or eid not in evidence:
                                raise ValueError("quote needs text and a real evidence_id")
                            evidence_row = evidence[eid]
                            annotations = {x.get("evidence_id"): x for x in source(source_name).get("annotations", []) if isinstance(x, dict)}
                            if annotations.get(eid, {}).get("status") != "admitted":
                                raise ValueError("quote source is not admitted")
                            if evidence_row.get("text_kind") in {"summary", "rewritten", "unknown"}:
                                raise ValueError("source text is not eligible for a direct quote")
                            if text not in evidence_row.get("text", ""):
                                raise ValueError("quote is not a continuous source substring")
                            if normalized(row["text"]) != normalized(text):
                                raise ValueError("displayed quote differs from its source binding")
                    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                        errors.append(label + ": " + str(exc))
                for kind in pools:
                    unused = set(pools[kind]) - seen[kind]
                    if unused:
                        errors.append(str(name) + ": declared " + kind + " bindings absent from HTML: " + ", ".join(sorted(unused)))
                if not parser.rows:
                    errors.append(str(name) + ": no binding elements; report linkage is unverified")
                summary["reports"] += 1
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(str(exc))

        spec_path = run / "research-spec.json"
        if spec_path.exists():
            spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
            for output in spec.get("outputs", []):
                if isinstance(output, dict) and isinstance(output.get("format"), str) and output["format"].lower() == "html" and output.get("bindings_required", True):
                    if output.get("path") not in checked:
                        errors.append("required report missing from bindings: " + str(output.get("path")))
                elif output == "html" and "report.html" not in checked:
                    errors.append("required report missing from bindings: report.html")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
    warnings.append("Static bindings do not verify interpretation, CSS visibility, interaction, PDF exports or visual quality.")
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
