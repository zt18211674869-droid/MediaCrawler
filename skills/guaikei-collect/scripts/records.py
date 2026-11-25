"""Normalize local GUAIKEI results. All identifiers stay as strings."""

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, urlencode, urlsplit


BEIJING = timezone(timedelta(hours=8))
POST_IDS = {"douyin": r"[1-9][0-9]*", "xiaohongshu": r"[a-fA-F0-9]{24}"}
AUTHOR_IDS = {"douyin": r"MS4wLjA[A-Za-z0-9_-]{1,173}", "xiaohongshu": r"(?:[a-fA-F0-9]{24}|[a-zA-Z0-9_-]{29})"}
POST_URL_FIELDS = ("url", "share_url", "note_url")


def _count(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value):
        value = int(value)
    return value if type(value) is int and value >= 0 else None


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _id(value):
    if type(value) is int:
        return str(value) if value > 0 else None
    value = _text(value)
    return value if value and value.casefold() not in {"0", "null", "none", "unknown"} else None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _time(value):
    stamp = _count(value)
    try:
        if stamp is not None:
            if not stamp:
                return None
            return datetime.fromtimestamp(stamp / 1000 if stamp >= 100_000_000_000 else stamp, BEIJING)
        if isinstance(value, str):
            date = datetime.fromisoformat(value.strip().replace("/", "-").replace("Z", "+00:00"))
            return date.replace(tzinfo=BEIJING) if date.tzinfo is None else date.astimezone(BEIJING)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _url_path(platform, value):
    try:
        link = urlsplit(value) if isinstance(value, str) else None
    except ValueError:
        return ""
    host = platform + ".com"
    if link and link.scheme == "https" and link.netloc.lower() in (host, "www." + host):
        return link.path.rstrip("/")
    return ""


def _author_id(platform, value):
    value = _text(value)
    if not value:
        return None
    pattern = AUTHOR_IDS[platform]
    if re.fullmatch(pattern, value):
        return value
    prefix = "/user/" if platform == "douyin" else "/user/profile/"
    match = re.fullmatch(prefix + "(" + pattern + ")", _url_path(platform, value))
    return match[1] if match else None


def _post_id(platform, row):
    value = _id(row.get("aweme_id") if platform == "douyin" else row.get("id") or row.get("note_id"))
    pattern = POST_IDS[platform]
    identifiers = {value.lower()} if value and re.fullmatch(pattern, value) else set()
    prefix = r"/(?:share/)?(?:video|note)/" if platform == "douyin" else r"/(?:explore|discovery/item)/"
    for key in POST_URL_FIELDS:
        if match := re.fullmatch(prefix + "(" + pattern + ")", _url_path(platform, row.get(key))):
            identifiers.add(match[1].lower())
    return next(iter(identifiers)) if len(identifiers) == 1 else None


def xhs_note_url(post_id, row):
    """Build a visitable link using only this note's own search or share token."""
    if not isinstance(post_id, str) or not re.fullmatch(POST_IDS["xiaohongshu"], post_id):
        return None
    post_id = post_id.lower()
    token = _text(row.get("xsec_token"))
    source = _text(row.get("xsec_source"))
    paths = {f"/explore/{post_id}", f"/discovery/item/{post_id}"}
    for key in POST_URL_FIELDS:
        url = row.get(key)
        if not url or _url_path("xiaohongshu", url).lower() not in paths:
            continue
        # A literal plus in a shared link belongs to the opaque token.
        query = parse_qs(urlsplit(url).query.replace("+", "%2B"))
        url_token = _text(query.get("xsec_token", [None])[0])
        if url_token and token and url_token != token:
            continue
        token = token or url_token
        source = source or _text(query.get("xsec_source", [None])[0])
        if token and source:
            break
    if not token:
        return None
    params = {"xsec_token": token}
    if source:
        params["xsec_source"] = source
    return f"https://www.xiaohongshu.com/explore/{post_id}?" + urlencode(params, quote_via=quote)


def _check_rows(platform, rows):
    if platform not in POST_IDS:
        raise ValueError("未知采集平台")
    if not isinstance(rows, list):
        raise ValueError("MCP 结果缺少有效列表")


def search_records(platform, rows, window):
    """Return unique posts inside the frozen [start,end) and coverage counters."""
    _check_rows(platform, rows)
    window = _mapping(window)
    start, end = _time(window.get("start")), _time(window.get("end"))
    if not start or not end or start >= end:
        raise ValueError("缺少有效的时间窗口")
    douyin = platform == "douyin"
    records = {}
    counts = {"raw_count": len(rows), "missing_id": 0, "outside_window": 0, "unresolved_time": 0,
              "duplicate_rows": 0, "uncertain_day_rows": 0}
    for raw in rows:
        row = _mapping(raw)
        identifier = _post_id(platform, row)
        if not identifier:
            counts["missing_id"] += 1
            continue
        time_fields = ("create_time_str", "publish_time", "create_time") if douyin else ("publish_time", "timestamp")
        times = [stamp for key in time_fields if (stamp := _time(row.get(key))) is not None]
        if times and (max(times) < start or min(times) >= end):
            counts["outside_window"] += 1
            continue
        if not times or min(times) < start or max(times) >= end:
            counts["unresolved_time"] += 1
            continue
        uncertain_day = len({stamp.date() for stamp in times}) > 1
        counts["uncertain_day_rows"] += int(uncertain_day)
        profile = _mapping(row.get("author" if douyin else "user"))
        author_ids = [row.get("author_sec_uid"), profile.get("sec_uid"), row.get("author_url")] if douyin else [profile.get("user_id")]
        locators = {loc for value in author_ids if (loc := _author_id(platform, value))}
        if douyin:
            is_note = row.get("images") or "/note/" in _url_path(platform, row.get("url"))
            url = f"https://www.douyin.com/{'note' if is_note else 'video'}/{identifier}"
        else:
            url = xhs_note_url(identifier, row)
        record = {
            "platform": platform, "post_id": identifier, "url": url,
            "author_id": next(iter(locators)) if len(locators) == 1 else None,
            "author_name": _text(row.get("author_nickname") if douyin else profile.get("nickname")),
            "title": _text(row.get("title")), "text": _text(row.get("desc")) or _text(row.get("content")),
            "published_at": times[0].isoformat(), "day_uncertain": uncertain_day,
            "comment_count": _count(row.get("comment_count")),
            "like_count": _count(row.get("digg_count" if douyin else "liked_count")),
        }
        if identifier in records:
            counts["duplicate_rows"] += 1
            prior = records[identifier]
            prior.update({key: val for key, val in record.items() if prior.get(key) is None and val is not None})
            prior["day_uncertain"] |= uncertain_day or prior["published_at"][:10] != record["published_at"][:10]
        else:
            records[identifier] = record
    counts["unique_count"] = len(records)
    return list(records.values()), counts


def comment_records(platform, post_id, rows, limit):
    """Flatten real nested replies, then cap roots and replies together."""
    _check_rows(platform, rows)
    post_id = _id(post_id)
    if not post_id or not re.fullmatch(POST_IDS[platform], post_id):
        raise ValueError("作品 ID 无效")
    if type(limit) is not int or not 1 <= limit <= 5000:
        raise ValueError("评论 limit 必须为 1 至 5000 的整数")
    douyin = platform == "douyin"
    child_key = "reply_comment" if douyin else "sub_comments"
    records = {}
    missing = 0
    duplicates = 0
    stack = [(row, None, None, 0) for row in reversed(rows)]
    while stack:
        raw, parent, root, depth = stack.pop()
        row = _mapping(raw)
        cid = _id(row.get("cid" if douyin else "id"))
        if depth == 0:
            root = cid
        if cid:
            user = _mapping(row.get("user"))
            stamp = _time(row.get("create_time")) or _time(row.get("create_time_str"))
            record = {
                "platform": platform, "post_id": post_id, "comment_id": cid, "parent_id": parent,
                "root_id": root, "depth": depth,
                "relation_source": child_key if depth else ("top_level" if douyin else "top_level_unspecified"),
                "text": _text(row.get("text" if douyin else "content")),
                "created_at": stamp.isoformat() if stamp else None,
                "author_name": _text(row.get("user_nickname") if douyin else user.get("nickname")),
                "like_count": _count(row.get("digg_count" if douyin else "like_count")),
                "reported_replies": _count(row.get("reply_comment_total" if douyin else "sub_comment_count")),
            }
            if cid in records:
                duplicates += 1
                prior = records[cid]
                if depth and not prior["depth"]:
                    records[cid] = record
                    record.update({k: v for k, v in prior.items() if record.get(k) is None and k not in ("parent_id", "root_id")})
                else:
                    prior.update({k: v for k, v in record.items() if prior.get(k) is None and k not in ("parent_id", "root_id")})
            else:
                records[cid] = record
        else:
            missing += 1
        children = row.get(child_key)
        if isinstance(children, list):
            stack.extend((child, cid, root, depth + 1) for child in reversed(children))

    selected = list(records.values())[:limit]
    top = [row for row in selected if row["depth"] == 0]
    replies = Counter(row["root_id"] for row in selected if row["depth"] > 0)
    gaps = [max(0, row["reported_replies"] - replies[row["comment_id"]]) for row in top if row["reported_replies"] is not None]
    reached = len(rows) >= limit or len(records) >= limit
    return selected, {
        "raw_count": len(rows), "unique_count": len(selected), "root_count": len(top),
        "reply_count": len(selected) - len(top), "missing_id": missing, "duplicate_rows": duplicates,
        "known_reply_gap": sum(gaps) if gaps else None, "roots_missing_reply_count": len(top) - len(gaps),
        "truncated_count": len(records) - len(selected), "limit_reached": reached,
        "coverage_status": "部分覆盖" if reached or any(gaps) or missing else "完整性未核实",
    }


def author_record(platform, locator, results):
    """Extract a public profile only when the response proves the same identity."""
    if platform not in AUTHOR_IDS:
        raise ValueError("未知采集平台")
    target = _author_id(platform, locator)
    user = _mapping(_mapping(results).get("user"))
    if not target or not user:
        raise ValueError("缺少有效主页标识或作者资料")
    douyin = platform == "douyin"
    evidence = ("sec_uid",) if douyin else ("user_id", "share_link")
    observed = [_author_id(platform, user[key]) for key in evidence if user.get(key)]
    if not observed or any(identity != target for identity in observed):
        raise ValueError("主页回包无法核实为请求的账号")
    stats = _mapping(user.get("note_num_stat"))
    fields = {
        "name": _text(user.get("nickname")), "public_id": _text(user.get("unique_id" if douyin else "red_id")),
        "bio": _text(user.get("signature" if douyin else "desc")),
        "followers": _count(user.get("follower_count" if douyin else "fans")),
        "following": _count(user.get("following_count" if douyin else "follows")),
        "likes_received": _count(user.get("total_favorited" if douyin else "liked")),
        "post_count": _count(user.get("aweme_count") if douyin else stats.get("posted")),
        "certification": _text(user.get("enterprise_verify_reason")) or _text(user.get("official_verify_desc")) or _text(user.get("custom_verify")),
    }
    if not any(value is not None for value in fields.values()):
        raise ValueError("账号资料缺少可保存的字段")
    return {"platform": platform, "author_id": target, **fields}
