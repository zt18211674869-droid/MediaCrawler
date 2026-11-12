"""Check local links and portable tests, then build a verified standalone skill ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile


def package(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.is_relative_to(source):
        raise ValueError("archive must be outside the skill source")
    if source.name != "social-voc-analysis" or not (source / "SKILL.md").is_file():
        raise ValueError("expected the standalone social-voc-analysis source")
    links = 0
    for path in source.rglob("*.md"):
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            resolved = (path.parent / target.split("#")[0]).resolve()
            if not resolved.is_relative_to(source) or not resolved.exists():
                raise ValueError("broken or external local reference: " + str(path) + " -> " + target)
            links += 1
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=source, capture_output=True, text=True, encoding="utf-8",
    )
    if completed.returncode:
        raise ValueError("local regression tests failed:\n" + completed.stdout + completed.stderr)
    files = sorted(p for p in source.rglob("*") if p.is_file()
                   and "__pycache__" not in p.parts and p.suffix != ".pyc")
    if output.exists():
        raise ValueError("archive already exists; choose a new output filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, source.name + "/" + path.relative_to(source).as_posix())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        for path in files:
            name = source.name + "/" + path.relative_to(source).as_posix()
            if archive.read(name) != path.read_bytes():
                raise ValueError("ZIP differs from source: " + name)
    return {"ok": True, "skill": source.name, "files": len(files), "local_links": links,
            "test_output": completed.stderr.strip(), "archive": str(output),
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = package(args.source, args.output)
    except (OSError, ValueError) as exc:
        result = {"ok": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
