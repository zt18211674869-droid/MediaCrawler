"""Record guaikei MCP task state locally; this tool never executes requests.

Usage: collection_ledger.py init RUN_DIR --target-count N --max-tasks N --max-tool-calls N
       collection_ledger.py record RUN_DIR REQUEST_JSON
       collection_ledger.py transition RUN_DIR REQUEST_ID EVENT_JSON
       collection_ledger.py status RUN_DIR
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path


STATES = {"planned", "submitted_pending", "timeout_pending", "submission_unknown", "complete", "failed"}
TRANSITIONS = {
    "planned": {"submitted_pending", "submission_unknown", "complete", "failed"},
    "submitted_pending": {"submitted_pending", "timeout_pending", "complete", "failed"},
    "timeout_pending": {"submitted_pending", "timeout_pending", "complete", "failed"},
    "submission_unknown": {"submitted_pending", "timeout_pending", "submission_unknown", "complete", "failed"},
    "complete": set(), "failed": set(),
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def nonnegative(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(label + " must be a nonnegative integer")
    return value


def clean(value):
    """Reject credentials, not business pagination fields such as cursor."""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower().replace("-", "_") in {"authorization", "api_key", "access_token", "password", "secret", "bearer_token"}:
                raise ValueError("credentials must not be stored in the collection ledger")
            clean(item)
    elif isinstance(value, list):
        for item in value:
            clean(item)
    elif isinstance(value, str) and value.strip().lower().startswith("bearer "):
        raise ValueError("bearer credentials must not be stored in the collection ledger")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite values are not valid ledger data")


def fingerprint(request):
    value = {"provider": "guaikei", "tool": request["tool"], "parameters": request["parameters"]}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def result_reference(run, value):
    if not isinstance(value, dict) or not isinstance(value.get("file"), str):
        raise ValueError("result_ref needs a local relative file")
    relative = Path(value["file"])
    path = (run / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(run.resolve()) or not path.is_file():
        raise ValueError("result_ref must identify an existing file inside RUN_DIR")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if "sha256" in value and value["sha256"] != digest:
        raise ValueError("result_ref SHA256 mismatch")
    return {"file": path.relative_to(run.resolve()).as_posix(), "sha256": digest}


@contextmanager
def locked(run):
    lock = run / ".collection-ledger.lock"
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("ledger is locked; inspect an interrupted operation before retrying") from None
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def save(path, doc):
    temporary = path.with_suffix(".json.pending")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def load(run):
    doc = json.loads((run / "collection-ledger.json").read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("schema_version") != "collection-ledger-v1" or doc.get("provider") != "guaikei":
        raise ValueError("unsupported ledger; only guaikei MCP is supported")
    clean(doc)
    return doc


def init(run_dir, target_count, max_tasks, max_tool_calls):
    run = Path(run_dir).resolve()
    for value, label in ((target_count, "target_count"), (max_tasks, "max_tasks"), (max_tool_calls, "max_tool_calls")):
        nonnegative(value, label)
    run.mkdir(parents=True, exist_ok=True)
    with locked(run):
        path = run / "collection-ledger.json"
        if path.exists():
            raise ValueError("ledger already exists; resume it instead of reinitializing")
        doc = {"schema_version": "collection-ledger-v1", "provider": "guaikei", "transport": "mcp",
               "created_at": timestamp(), "target_count": target_count,
               "budget": {"max_tasks": max_tasks, "max_tool_calls": max_tool_calls}, "requests": []}
        save(path, doc)
    return doc


def record(run_dir, request):
    run = Path(run_dir).resolve()
    clean(request)
    if not isinstance(request, dict) or request.get("provider", "guaikei") != "guaikei":
        raise ValueError("request provider must be guaikei")
    for key in ("request_id", "tool"):
        if not isinstance(request.get(key), str) or not request[key].strip():
            raise ValueError("request needs " + key)
    if not isinstance(request.get("parameters"), dict):
        raise ValueError("parameters must be an explicit object")
    for key in ("target_count", "effective_limit"):
        if key in request and request[key] is not None:
            nonnegative(request[key], key)
    with locked(run):
        doc = load(run)
        digest = fingerprint(request)
        if any(row["request_id"] == request["request_id"] or row["fingerprint"] == digest for row in doc["requests"]):
            raise ValueError("duplicate request ID or parameters; resume the recorded task, do not recreate it")
        if len(doc["requests"]) >= doc["budget"]["max_tasks"]:
            raise ValueError("task budget exhausted")
        row = {"request_id": request["request_id"], "tool": request["tool"], "parameters": request["parameters"],
               "target_count": request.get("target_count"), "effective_limit": request.get("effective_limit"),
               "fingerprint": digest, "state": "planned", "created_at": timestamp(), "events": []}
        doc["requests"].append(row)
        save(run / "collection-ledger.json", doc)
    return row


def transition(run_dir, request_id, event):
    run = Path(run_dir).resolve()
    clean(event)
    if not isinstance(event, dict) or event.get("state") not in STATES or not isinstance(event.get("reason"), str) or not event["reason"].strip():
        raise ValueError("event needs a supported state and specific reason")
    action = event.get("action")
    if action not in {"submit", "query", "observe"}:
        raise ValueError("action must be submit, query or observe")
    calls = nonnegative(event.get("tool_calls", 0 if action == "observe" else 1), "tool_calls")
    if (action == "observe" and calls != 0) or (action != "observe" and calls < 1):
        raise ValueError("observations use zero calls; submitted/query actions need observed tool calls")
    http = event.get("http_requests")
    if http is not None:
        nonnegative(http, "http_requests")
    returned = event.get("returned_count")
    if returned is not None:
        nonnegative(returned, "returned_count")
    fee = event.get("fee")
    if fee is not None:
        if not isinstance(fee, dict) or type(fee.get("amount")) not in (int, float) or not math.isfinite(fee["amount"]) or fee["amount"] < 0 or not isinstance(fee.get("currency"), str) or not fee["currency"].strip():
            raise ValueError("fee must be null or observed nonnegative amount with currency")
    with locked(run):
        doc = load(run)
        row = next((r for r in doc["requests"] if r["request_id"] == request_id), None)
        if row is None:
            raise ValueError("unknown request_id")
        prior, state = row["state"], event["state"]
        if state not in TRANSITIONS[prior]:
            raise ValueError("invalid state transition: " + prior + " -> " + state)
        if action == "submit" and prior != "planned":
            raise ValueError("a submitted or uncertain task cannot be submitted again")
        if prior == "planned" and action != "submit":
            raise ValueError("planned requests must first record the actual submission")
        if action == "observe" and state != "timeout_pending":
            raise ValueError("an observation can only record a still-pending deadline")
        if action == "query" and event.get("query_supported") is not True:
            raise ValueError("query recovery requires an actually available query capability")
        if prior == "submission_unknown" and action != "query":
            raise ValueError("unknown submissions can only recover through a supported query")
        used = sum(e["tool_calls"] for r in doc["requests"] for e in r["events"])
        if used + calls > doc["budget"]["max_tool_calls"]:
            raise ValueError("tool-call budget exhausted; no state changed")
        reference = result_reference(run, event["result_ref"]) if "result_ref" in event else None
        if state == "complete" and reference is None:
            raise ValueError("complete requires a saved result_ref, not a completion assertion")
        if prior == "submission_unknown" and reference is None:
            raise ValueError("unknown-submission recovery needs saved query evidence")
        task_id = event.get("provider_task_id")
        if task_id is not None and (not isinstance(task_id, str) or not task_id.strip()):
            raise ValueError("provider_task_id must preserve a nonempty string")
        stored = {"at": timestamp(), "from_state": prior, "state": state, "action": action,
                  "reason": event["reason"], "tool_calls": calls, "http_requests": http, "fee": fee,
                  "returned_count": returned}
        if action == "query":
            stored["query_supported"] = True
        if reference:
            stored["result_ref"] = reference
        if task_id is not None:
            if row.get("provider_task_id") not in (None, task_id):
                raise ValueError("provider_task_id cannot change during recovery")
            row["provider_task_id"] = task_id
        row["events"].append(stored)
        row["state"] = state
        save(run / "collection-ledger.json", doc)
    return row


def status(run_dir):
    run = Path(run_dir).resolve()
    doc = load(run)
    events = [e for row in doc["requests"] for e in row["events"]]
    for event in events:
        if "result_ref" in event:
            result_reference(run, event["result_ref"])
    return {"provider": "guaikei", "target_count": doc["target_count"], "task_count": len(doc["requests"]),
            "tool_calls": sum(e["tool_calls"] for e in events),
            "http_requests": sum(e["http_requests"] for e in events) if all(e["http_requests"] is not None for e in events) else None,
            "budget": doc["budget"], "states": {row["request_id"]: row["state"] for row in doc["requests"]},
            "limits": "Local journal only; tool calls do not establish HTTP counts, fees or remote idempotency."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    initial = sub.add_parser("init")
    initial.add_argument("run_dir", type=Path)
    for flag in ("target-count", "max-tasks", "max-tool-calls"):
        initial.add_argument("--" + flag, type=int, required=True)
    request = sub.add_parser("record")
    request.add_argument("run_dir", type=Path)
    request.add_argument("request_json", type=Path)
    update = sub.add_parser("transition")
    update.add_argument("run_dir", type=Path)
    update.add_argument("request_id")
    update.add_argument("event_json", type=Path)
    view = sub.add_parser("status")
    view.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            value = init(args.run_dir, args.target_count, args.max_tasks, args.max_tool_calls)
        elif args.command == "record":
            value = record(args.run_dir, json.loads(args.request_json.read_text(encoding="utf-8-sig")))
        elif args.command == "transition":
            value = transition(args.run_dir, args.request_id, json.loads(args.event_json.read_text(encoding="utf-8-sig")))
        else:
            value = status(args.run_dir)
        result = {"ok": True, "result": value, "network_calls_performed": 0}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = {"ok": False, "errors": [str(exc)], "network_calls_performed": 0}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
