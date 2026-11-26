"""Find independent nickname evidence for a selected Xiaohongshu post author."""

import json
from functools import lru_cache

from records import _author_id, _post_id, comment_records, search_records


def nickname_evidence(db, root, plan, *, envelope, raw_path):
    """Return a lazy lookup shared by the author jobs in one reconciliation pass."""
    platform = "xiaohongshu"

    @lru_cache(maxsize=1)
    def post_owners():
        owners = {}
        for post_id, payload in db.execute(
                "SELECT item_key, payload FROM items WHERE kind='posts' AND platform=?", (platform,)):
            post = json.loads(payload)
            locator = post.get("author_id")
            if isinstance(locator, str) and len(locator) == 29 and not post.get("author_conflict"):
                owners[post_id] = locator
        return owners, set(owners.values())

    def completed_archives(kind, tool):
        jobs = db.execute("SELECT id, attempt, args, target FROM jobs WHERE state='done' AND kind=? AND tool=?",
                          (kind, tool))
        for job in jobs:
            try:
                response = envelope(raw_path(root, job))
                limit = json.loads(job["args"])["limit"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if type(limit) is not int or not 1 <= limit <= 5000 or not isinstance(response, dict):
                continue
            if response.get("status") != "success" or str(response.get("error_code") or "").upper() not in ("", "OK", "0"):
                continue
            rows = response.get("results")
            if not isinstance(rows, list):
                continue
            request = response.get("request")
            if isinstance(request, dict):
                if request.get("command", tool) != tool:
                    continue
                if kind == "search" and request.get("keyword", job["target"]) != job["target"]:
                    continue
                if kind == "comment" and any(
                    _post_id(platform, {"id": request[k], "url": request[k]}) != job["target"]
                    for k in ("url", "url_raw") if request.get(k)
                ):
                    continue
            yield job["target"], limit, rows

    @lru_cache(maxsize=1)
    def post_names():
        owners, selected = post_owners()
        names = set()
        for _, limit, rows in completed_archives("search", "xiaohongshu_note_search"):
            for row in rows[:limit]:
                user = row.get("user") if isinstance(row, dict) else None
                if not isinstance(user, dict):
                    continue
                locator = _author_id(platform, user.get("user_id"))
                if locator not in selected or not user.get("nickname"):
                    continue
                # Normalize a single observation so one duplicate cannot supply the ID
                # and another the name, or contribute a nickname outside the time window.
                posts, _ = search_records(platform, [row], plan["window"])
                if posts and owners.get(posts[0]["post_id"]) == locator and posts[0]["author_name"]:
                    names.add((locator, posts[0]["author_name"]))
        return names

    @lru_cache(maxsize=1)
    def comment_names():
        _, selected = post_owners()
        names = set()
        for post_id, limit, rows in completed_archives("comment", "xiaohongshu_comment"):
            try:
                comments, _ = comment_records(platform, post_id, rows, limit)
            except (ValueError, TypeError, OverflowError):
                continue
            for comment in comments:
                locator, name = comment.get("author_id"), comment.get("author_name")
                if locator in selected and name:
                    names.add((locator, name))
        return names

    def lookup(locator, nickname):
        if not plan["config"]["include_authors"] or locator not in post_owners()[1]:
            return None
        pair = (locator, nickname.strip())
        if pair in post_names():
            return "original_receipt_and_post_nickname"
        if plan["config"]["include_comments"] and pair in comment_names():
            return "original_receipt_and_comment_nickname"
        return None

    return lookup
