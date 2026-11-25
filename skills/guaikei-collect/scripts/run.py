"""Local checkpoint and export for a host calling its installed GUAIKEI MCP tools."""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from excel_report import write_workbook
from plan import MAX_CONCURRENCY, build_plan
from records import author_record, comment_records, search_records, xhs_note_url


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def add_job(db, kind, tool, target, args):
    db.execute(
        "INSERT OR IGNORE INTO jobs(kind,tool,target,args) VALUES(?,?,?,?)",
        (kind, tool, target, dump(args)),
    )


def initialize(root, config):
    return initialize_from_config(root, read(config))


def initialize_from_config(root, config, *, available_tools=None):
    plan = build_plan(config)
    if available_tools is not None:
        required = {search["tool"] for search in plan["searches"]}
        for branch in plan["enrichment"].values():
            if branch["enabled"]:
                required.update(branch["tools"].values())
        missing = sorted(required - available_tools)
        if missing:
            raise ValueError("当前连接缺少勾选的工具：" + "、".join(missing))
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    (root / "plan.json").write_text(dump(plan), encoding="utf-8")
    with sqlite3.connect(root / "run.sqlite3") as db:
        db.executescript("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY, kind TEXT, tool TEXT, target TEXT, args TEXT,
                state TEXT DEFAULT 'queued', attempt INTEGER DEFAULT 0, receipt TEXT,
                detail TEXT, observed TEXT, UNIQUE(tool,target)
            );
            CREATE TABLE items (
                kind TEXT, platform TEXT, item_key TEXT, payload TEXT,
                PRIMARY KEY(kind,platform,item_key)
            );
            CREATE TABLE progress (followups_ready INTEGER);
            INSERT INTO progress VALUES(0);
            PRAGMA user_version=1;
        """)
        for query in plan["searches"]:
            add_job(db, "search", query["tool"], query["args"]["keyword"], query["args"])
    return {"run": str(root), "window": plan["window"], "estimated": plan["estimated"]}


def store(db, kind, platform, key, record):
    db.execute("INSERT OR REPLACE INTO items VALUES(?,?,?,?)",
               (kind, platform, key, dump({**record, "platform": platform})))


def merge_post(db, platform, record, keyword):
    post_id = record["post_id"]
    match = db.execute("SELECT payload FROM items WHERE kind='posts' AND platform=? AND item_key=?",
                       (platform, post_id)).fetchone()
    previous = json.loads(match[0]) if match else {}
    merged = {**previous, **{k: v for k, v in record.items() if v is not None}}
    if platform == "xiaohongshu":
        merged["url"] = record["url"] or xhs_note_url(post_id, previous)
    old_author, new_author = previous.get("author_id"), record.get("author_id")
    if previous.get("author_conflict") or (old_author and new_author and old_author != new_author):
        merged.update(author_conflict=True, author_id=None)
    merged["day_uncertain"] = bool(previous.get("day_uncertain") or record.get("day_uncertain")
                                   or (previous.get("published_at") and
                                       previous["published_at"][:10] != record["published_at"][:10]))
    merged["keywords"] = list(dict.fromkeys([*previous.get("keywords", []), keyword]))
    store(db, "posts", platform, post_id, merged)
    db.execute("UPDATE progress SET followups_ready=0 WHERE followups_ready=1")


def materialize(db, job, data, plan):
    platform = job["tool"].split("_", 1)[0]
    if job["kind"] == "author":
        author = author_record(platform, job["target"], data)
        store(db, "authors", platform, job["target"], author)
        return {"authors": 1}
    if not isinstance(data, list):
        raise ValueError("结果缺少列表")
    if job["kind"] == "search":
        limit = json.loads(job["args"])["limit"]
        posts, counts = search_records(platform, data[:limit], plan["window"])
        for post in posts:
            merge_post(db, platform, post, job["target"])
        counts.update(raw_count=len(data), above_request_limit=max(0, len(data) - limit),
                      request_limit_reached=len(data) >= limit)
        return counts
    comments, counts = comment_records(platform, job["target"], data, json.loads(job["args"])["limit"])
    for item in comments:
        key = dump([job["target"], item["comment_id"]])
        store(db, "comments", platform, key, item)
    return counts


def envelope(path):
    data = read(path)
    if isinstance(data, dict) and "status" in data:
        return data
    # Preserve integer IDs from the original MCP text with Python's JSON parser.
    if isinstance(data, dict):
        for block in data.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            try:
                parsed = json.loads(block["text"])
                if isinstance(parsed, dict) and "status" in parsed:
                    return parsed
            except (KeyError, ValueError, TypeError):
                continue
        structured = data.get("structuredContent")
        if isinstance(structured, dict) and "status" in structured:
            return structured
    raise ValueError("回包格式待核")


def receipt_id(response):
    request = response.get("request")
    value = request.get("id") if isinstance(request, dict) else None
    try:
        return str(UUID(str(value)))
    except ValueError:
        return None


def raw_path(root, job):
    return root / "raw" / f"{job['id']:06d}-{job['attempt']}.json"


def upgrade_note_links(db, root, plan):
    if db.execute("PRAGMA user_version").fetchone()[0] >= 1:
        return

    posts = "kind='posts' AND platform='xiaohongshu'"
    unresolved = set()
    for post_id, payload in db.execute(f"SELECT item_key, payload FROM items WHERE {posts}"):
        item = json.loads(payload)
        url = xhs_note_url(post_id, item)
        if "url" not in item or item["url"] != url:
            item["url"] = url
            db.execute(f"UPDATE items SET payload=? WHERE {posts} AND item_key=?", (dump(item), post_id))
        if not url:
            unresolved.add(post_id)

    # Recover only links of already admitted posts; do not replay jobs or enrichment.
    # Prefer the most recently observed signed link if multiple searches hit the same note.
    archives_complete = True
    for job in db.execute("""SELECT id, attempt, args FROM jobs WHERE state='done' AND kind='search'
                             AND tool='xiaohongshu_note_search' ORDER BY observed DESC, id DESC"""):
        if not unresolved:
            break
        try:
            result = envelope(raw_path(root, job))
            rows = result.get("results")
            code = str(result.get("error_code") or "").upper()
            if result.get("status") != "success" or code not in ("", "OK", "0") or not isinstance(rows, list):
                archives_complete = False
                continue
            limit = json.loads(job["args"])["limit"]
            records, _ = search_records("xiaohongshu", rows[:limit], plan["window"])
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            archives_complete = False
            continue
        for record in records:
            key = record["post_id"]
            if key in unresolved and record["url"]:
                previous = db.execute(f"SELECT payload FROM items WHERE {posts} AND item_key=?", (key,)).fetchone()
                item = json.loads(previous[0])
                item["url"] = record["url"]
                db.execute(f"UPDATE items SET payload=? WHERE {posts} AND item_key=?", (dump(item), key))
                unresolved.remove(key)

    # A temporarily missing archive may be restored before the next offline export.
    if archives_complete or not unresolved:
        db.execute("PRAGMA user_version=1")


def reconcile(db, root, plan):
    for job in db.execute("SELECT * FROM jobs WHERE state='issued' ORDER BY id").fetchall():
        path = raw_path(root, job)
        if not path.is_file():
            continue
        receipt = job["receipt"]
        db.execute("SAVEPOINT intake")
        try:
            result = envelope(path)
            code = str(result.get("error_code") or "").upper()
            receipt = receipt_id(result) or receipt
            if result.get("status") == "success" and code in ("", "OK", "0"):
                detail = materialize(db, job, result.get("results"), plan)
                state = "done"
            else:
                detail = {"error_code": code or "UNKNOWN"}
                if code == "TIMEOUT" and receipt:
                    state = "poll" if job["attempt"] == 1 else "pending"
                elif code.startswith("AUTH") or code in ("17", "401", "403", "INSUFFICIENT_BALANCE", "INSUFFICIENT_CREDITS", "QUOTA_EXCEEDED") or "余额" in str(result.get("message") or ""):
                    state = "blocked"
                elif code in ("429", "RATE_LIMITED", "RATE_LIMIT"):
                    state = "rate_limited"
                elif code in ("INVALID_ARGS", "INVALID_URL"):
                    state = "invalid"
                else:
                    state = "needs_review"
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            db.execute("ROLLBACK TO intake")
            state, detail = "needs_review", {"reason": str(error)[:160]}
        db.execute("RELEASE intake")
        db.execute("UPDATE jobs SET state=?, receipt=?, detail=?, observed=? WHERE id=?",
                   (state, receipt, dump(detail), datetime.now(timezone.utc).isoformat(), job["id"]))


def make_followups(db, config):
    for row in db.execute("SELECT platform,item_key,payload FROM items WHERE kind='posts'"):
        platform, post_id, payload = row
        post = json.loads(payload)
        count = post.get("comment_count")
        if config["include_comments"] and count != 0:
            limit = config["comment_limit"] if count is None else min(config["comment_limit"], count)
            add_job(db, "comment", platform + "_comment", post_id, {"url": post_id, "limit": limit})
        if config["include_authors"] and post.get("author_id"):
            locator = post["author_id"]
            add_job(db, "author", platform + "_post", locator, {"url": locator, "limit": 0})


def states(db):
    return dict(db.execute("SELECT state,count(*) FROM jobs GROUP BY state").fetchall())


def claim(db, root, plan):
    config = plan["config"]
    status = states(db)
    if status.get("blocked") or status.get("rate_limited"):
        return {"jobs": [], "states": status, "stopped": True}
    # Older plans may have allowed up to 20 jobs; keep their frozen source configuration.
    capacity = min(config["concurrency"], MAX_CONCURRENCY)
    slots = max(0, capacity - status.get("issued", 0))
    active_search = db.execute("""SELECT 1 FROM jobs WHERE kind='search'
                                  AND state IN ('queued','issued','poll') LIMIT 1""").fetchone()
    if not active_search and not db.execute("SELECT followups_ready FROM progress").fetchone()[0]:
        make_followups(db, config)
        db.execute("UPDATE progress SET followups_ready=1")
    batch = []
    # Polling an existing receipt can settle upstream work even when unresolved jobs
    # already occupy the full capacity. Only unused upstream slots admit a new request.
    jobs = db.execute("SELECT * FROM jobs WHERE state='poll' ORDER BY id LIMIT ?", (slots,)).fetchall()
    new_slots = max(0, slots - len(jobs) - status.get("pending", 0))
    jobs.extend(db.execute("""SELECT * FROM jobs WHERE state='queued' AND (kind='search' OR ?)
                              ORDER BY id LIMIT ?""", (not active_search, new_slots)))
    for job in jobs:
        attempt = job["attempt"] + 1
        db.execute("UPDATE jobs SET state='issued',attempt=? WHERE id=?", (attempt, job["id"]))
        path = raw_path(root, {**dict(job), "attempt": attempt})
        batch.append({"tool": job["tool"], "args": {"id": job["receipt"]} if job["state"] == "poll"
                      else json.loads(job["args"]), "output": path.as_posix()})
    return {"jobs": batch, "states": states(db)}


def export(db, root, plan):
    upgrade_note_links(db, root, plan)
    counts = {}
    config = plan["config"]
    platforms = {name: dict.fromkeys(("posts", "comments", "replies", "authors",
                                     "zero_comment_posts", "missing_author_locator",
                                     "unresolved_time_hits", "search_limit_hits", "comment_limit_hits",
                                     "known_missing_replies_lower_bound"), 0) for name in config["platforms"]}
    for kind in ("posts", "comments", "authors"):
        with (root / f"{kind}.jsonl").open("w", encoding="utf-8") as output:
            counts[kind] = 0
            for row in db.execute("SELECT platform,payload FROM items WHERE kind=? ORDER BY platform,item_key", (kind,)):
                output.write(row["payload"] + "\n")
                counts[kind] += 1
                item = json.loads(row["payload"])
                stats = platforms[row["platform"]]
                if kind == "posts":
                    stats["posts"] += 1
                    stats["zero_comment_posts"] += int(item.get("comment_count") == 0)
                    stats["missing_author_locator"] += int(not item.get("author_id"))
                elif kind == "comments":
                    stats["replies" if item["depth"] > 0 else "comments"] += 1
                else:
                    stats["authors"] += 1
    issues = Counter()
    with (root / "tasks.jsonl").open("w", encoding="utf-8") as output:
        for row in db.execute("SELECT * FROM jobs ORDER BY id"):
            job = dict(row)
            job["args"] = json.loads(job["args"])
            job["detail"] = json.loads(job["detail"]) if job["detail"] else None
            job["raw"] = str(raw_path(root, job).relative_to(root)) if job["attempt"] else None
            output.write(dump(job) + "\n")
            if job["state"] != "done":
                issues[job["kind"]] += 1
            else:
                stats = platforms[job["tool"].split("_", 1)[0]]
                detail = job["detail"]
                stats["unresolved_time_hits"] += detail.get("unresolved_time", 0)
                stats["search_limit_hits"] += int(detail.get("request_limit_reached", False))
                stats["comment_limit_hits"] += int(detail.get("limit_reached", False))
                stats["known_missing_replies_lower_bound"] += detail.get("known_reply_gap") or 0
    summary = {"window": plan["window"], "counts": counts, "tasks": states(db),
               "selected": {"comments": config["include_comments"], "authors": config["include_authors"]},
               "by_platform": platforms, "unfinished_by_kind": dict(issues),
               "coverage": "本轮已发现的候选；平台总量未知", "directory": str(root)}
    try:
        workbook = write_workbook(root, plan, summary, note=plan.get("sample_note"))
        summary["workbook"] = str(workbook)
    except PermissionError as error:
        raise OSError("无法写入采集结果.xlsx。请关闭已打开的工作簿并确认运行目录可写，再执行 report。") from error
    finally:
        (root / "summary.json").write_text(dump(summary), encoding="utf-8")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    parsers = ap.add_subparsers(dest="action", required=True)
    init = parsers.add_parser("init")
    init.add_argument("config", type=Path)
    for parser in (init, parsers.add_parser("next"), parsers.add_parser("report"), parsers.add_parser("resume")):
        parser.add_argument("run", type=Path)
    args = ap.parse_args()
    root = args.run.resolve()
    try:
        if args.action == "init":
            result = initialize(root, args.config)
        else:
            plan = read(root / "plan.json")
            if not (root / "run.sqlite3").is_file():
                raise ValueError("缺少本轮任务台账")
            with sqlite3.connect(root / "run.sqlite3") as db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN IMMEDIATE")
                reconcile(db, root, plan)
                if args.action == "next":
                    result = claim(db, root, plan)
                elif args.action == "resume":
                    # Only explicitly resume a known upstream task. Never resubmit unknown work.
                    db.execute("UPDATE jobs SET state='poll' WHERE state='pending' AND receipt IS NOT NULL")
                    db.execute("UPDATE jobs SET state='needs_review' WHERE state IN ('blocked','rate_limited')")
                    result = {"states": states(db)}
                else:
                    result = export(db, root, plan)
        sys.stdout.buffer.write((dump(result) + "\n").encode("utf-8"))
    except (OSError, ValueError, sqlite3.Error) as error:
        sys.stderr.buffer.write((str(error) + "\n").encode("utf-8"))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
