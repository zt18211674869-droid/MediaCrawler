"""Validate a collection form and generate a bounded GUAIKEI MCP search plan."""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


BEIJING = timezone(timedelta(hours=8))
PLATFORMS = ("douyin", "xiaohongshu")
MAX_CONCURRENCY = 10
FIELDS = {
    "keywords", "platforms", "days", "include_comments", "include_authors",
    "search_limit", "comment_limit", "concurrency",
}
LINK = re.compile(
    r"[a-z][a-z0-9+.-]*://|(?:^|\s)(?:www\.|//)|"
    r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?=$|[/:?#\s])",
    re.IGNORECASE,
)


def _keywords(value):
    if not isinstance(value, str):
        raise ValueError("keywords 必须是用逗号分隔的文本")
    if ";" in value or "；" in value:
        raise ValueError("请用中文或英文逗号分隔关键词，分号不支持")
    words = list(dict.fromkeys(
        part.strip() for part in re.split(r"[,，、\r\n]+", value) if part.strip()
    ))
    if not 1 <= len(words) <= 100:
        raise ValueError("请填写 1 至 100 个不同的关键词")
    for index, word in enumerate(words, start=1):
        if not 2 <= len(word) <= 50:
            raise ValueError(f"第 {index} 个关键词须为 2 至 50 个字符")
        if LINK.search(word) or any(char in word for char in """<>"'&"""):
            raise ValueError(f"第 {index} 个关键词含链接或不支持的字符")
    return words


def _integer(config, key, default, lower, upper):
    value = config.get(key, default)
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{key} 必须是 {lower} 至 {upper} 的整数")
    return value


def build_plan(config, *, now=None):
    """Return a validated, JSON-serializable plan; no network or file I/O."""
    if not isinstance(config, dict):
        raise ValueError("配置必须是 JSON 对象")
    if set(config) - FIELDS:
        raise ValueError("配置含未识别的字段，可用字段见问卷")

    words = _keywords(config.get("keywords"))
    platforms = config.get("platforms")
    if not isinstance(platforms, list) or not platforms or any(p not in PLATFORMS for p in platforms):
        raise ValueError("platforms 必须是非空数组，可选 douyin、xiaohongshu")
    platforms = list(dict.fromkeys(platforms))
    days = config.get("days")
    if type(days) is not int or days not in (1, 7, 15, 180):
        raise ValueError("days 必须是 1、7、15 或 180")
    for flag in ("include_comments", "include_authors"):
        if type(config.get(flag)) is not bool:
            raise ValueError(f"{flag} 必须是布尔值 true 或 false")
    search_limit = _integer(config, "search_limit", 1000, 1, 5000)
    comment_limit = _integer(config, "comment_limit", 5000, 1, 5000)
    concurrency = _integer(config, "concurrency", MAX_CONCURRENCY, 1, MAX_CONCURRENCY)

    end = datetime.now(BEIJING) if now is None else now
    if not isinstance(end, datetime) or end.utcoffset() is None:
        raise ValueError("now 必须是带时区的 datetime")
    end = end.astimezone(BEIJING)
    start = end - timedelta(days=days)

    searches = []
    for word in words:
        for platform in platforms:
            if platform == "douyin":
                tool = "douyin_general_search"
                args = {"sort": 2, "time": 180 if days == 15 else days}
            else:
                tool = "xiaohongshu_note_search"
                args = {"sort": 1, "time": {1: 1, 7: 2, 15: 3, 180: 3}[days]}
            searches.append({"tool": tool, "args": {"keyword": word, "limit": search_limit, **args}})

    candidate_max = len(searches) * search_limit
    return {
        "config": {
            "keywords": ", ".join(words), "platforms": platforms, "days": days,
            "include_comments": config["include_comments"], "include_authors": config["include_authors"],
            "search_limit": search_limit, "comment_limit": comment_limit, "concurrency": concurrency,
        },
        "window": {"start": start.isoformat(), "end": end.isoformat(), "bounds": "[start,end)"},
        "searches": searches,
        "enrichment": {
            "comments": {
                "enabled": config["include_comments"], "per": "unique_in_window_post",
                "tools": {p: f"{p}_comment" for p in platforms}, "limit": comment_limit,
            },
            "authors": {
                "enabled": config["include_authors"], "per": "unique_main_post_author",
                "tools": {p: f"{p}_post" for p in platforms}, "limit": 0,
            },
        },
        "estimated": {
            "search_calls": len(searches),
            "search_rows_requested_max": candidate_max,
            "comment_calls_max": candidate_max if config["include_comments"] else 0,
            "comment_rows_requested_max": candidate_max * comment_limit if config["include_comments"] else 0,
            "author_calls_max": candidate_max if config["include_authors"] else 0,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="UTF-8 JSON 配置文件路径，用 - 从标准输入读取")
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read() if args.config == "-" else Path(args.config).read_bytes()
        plan = build_plan(json.loads(raw.decode("utf-8-sig")))
    except (OSError, ValueError) as error:
        sys.stderr.buffer.write(f"配置错误：{error}\n".encode("utf-8"))
        return 2
    sys.stdout.buffer.write((json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
