"""Populate the packaged Excel template from a single run's normalized JSONL files."""

import json
import os
import posixpath
import re
import sqlite3
import tempfile
import unicodedata
from contextlib import closing
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from records import xhs_note_url

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "report-template.xlsx"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
ET.register_namespace("", MAIN)
ET.register_namespace("r", DOC)
MAX_DATA_ROWS = 1_048_576 - 3
PLATFORMS = {"douyin": "抖音", "xiaohongshu": "小红书"}
KINDS = {"search": "搜索主帖", "comment": "获取评论", "author": "获取主帖作者"}
STATES = {"queued": "待执行", "issued": "等待回包", "poll": "待按原回执续查", "pending": "待续查",
          "done": "已完成", "blocked": "已阻塞", "rate_limited": "受限流", "invalid": "参数无效",
          "needs_review": "待核实"}
SHEETS = (("主帖", "posts", 12), ("评论与回复", "comments", 11),
          ("主帖作者", "authors", 10), ("任务记录", "tasks", 11))
ILLEGAL = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\uD800-\uDFFF\uFFFE\uFFFF]")
BJT = timezone(timedelta(hours=8))
EPOCH = datetime(1899, 12, 30)


def tag(name):
    return f"{{{MAIN}}}{name}"


def sheet_xml(node):
    return ET.tostring(node, encoding="utf-8", xml_declaration=True)


def read_rows(root, table):
    with (root / (table + ".jsonl")).open(encoding="utf-8-sig") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def local_time(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return date.astimezone(BJT).replace(tzinfo=None) if date.tzinfo else date
    except ValueError:
        return None


def text_value(value):
    value = ILLEGAL.sub("", str(value))
    # Excel counts UTF-16 units; do not split a supplementary character.
    if len(value) > 16383:
        value = value.encode("utf-16-le")[:65534].decode("utf-16-le", errors="ignore")
    return value


def cell_xml(ref, style, value):
    attrs = f'r="{ref}" s="{style}"'
    if value is None:
        return f"<c {attrs}/>"
    if isinstance(value, datetime):
        value = (value - EPOCH).total_seconds() / 86400
    if type(value) in (int, float) and abs(value) < 10**15:
        return f"<c {attrs}><v>{value}</v></c>"
    # inlineStr preserves leading =, +, @ and long numeric-looking identifiers as data.
    return f'<c {attrs} t="inlineStr"><is><t xml:space="preserve">{escape(text_value(value))}</t></is></c>'


def replace_cell(sheet, ref, value):
    cell = sheet.find(f".//{tag('sheetData')}/{tag('row')}/{tag('c')}[@r='{ref}']")
    if cell is None:
        raise ValueError("工作簿模板缺少单元格 " + ref)
    node = ET.fromstring(f'<root xmlns="{MAIN}">' + cell_xml(ref, cell.get("s", "0"), value) + "</root>")[0]
    cell.clear()
    cell.attrib.update(node.attrib)
    cell.extend(list(node))


def make_overview(sheet, plan, summary, note):
    dimension = worksheet_child(sheet, "dimension", ("sheetViews", "sheetFormatPr", "cols", "sheetData"))
    dimension.set("ref", "A1:H18")
    config, stats = plan["config"], summary["by_platform"]
    comments, authors = config["include_comments"], config["include_authors"]
    start, end = (local_time(summary["window"][key]) for key in ("start", "end"))
    yes = lambda enabled: "开启" if enabled else "关闭"
    gaps = sum(x["known_missing_replies_lower_bound"] for x in stats.values())
    reply_status = f"已知缺失回复至少 {gaps:,} 条" if gaps else "未发现可量化的回复缺口，完整性未核实"
    values = {
        "B4": f"主帖发布时间（北京时间）   {start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M}，截止时刻不含在内",
        "B5": "检索关键词   " + config["keywords"],
        "B6": (f"每组搜索 {config['search_limit']:,} 篇  ·  评论{yes(comments)}"
               + (f"（每帖上限 {config['comment_limit']:,} 条）" if comments else "")
               + f"  ·  作者资料{yes(authors)}  ·  并发 {config['concurrency']}"),
        "B15": f"发布时间待核 {sum(x['unresolved_time_hits'] for x in stats.values()):,} 次命中"
               + "  ·  " + (reply_status if comments else "本轮未选评论"),
        "B16": "未完成任务   " + ("、".join(f"{KINDS.get(k, k)} {v:,} 项" for k, v in summary["unfinished_by_kind"].items()) or "0 项"),
        "B17": summary["coverage"] + "。触顶按请求次数统计；缺口为已知下界。",
        "B18": note or None,
    }
    keys = ("posts", "comments", "replies", "authors", "search_limit_hits", "comment_limit_hits")
    platforms = list(config["platforms"])
    for row, platform in ((9, platforms[0]), (10, platforms[1] if len(platforms) > 1 else None), (11, "total")):
        values[f"B{row}"] = "合计" if platform == "total" else PLATFORMS.get(platform)
        for col, key, enabled in zip("CDEFGH", keys, (True, comments, comments, authors, True, comments)):
            if platform is None:
                value = None
            elif not enabled:
                value = "—"
            else:
                value = sum(x[key] for x in stats.values()) if platform == "total" else stats[platform][key]
            values[f"{col}{row}"] = value
    for ref, value in values.items():
        replace_cell(sheet, ref, value)
        if ref in {"B4", "B5", "B6", "B15", "B16", "B17", "B18"} and value:
            row = sheet.find(f"{tag('sheetData')}/{tag('row')}[@r='{ref[1:]}']")
            # Merged overview cells span roughly 96 Latin glyphs. Excel does not
            # auto-fit merged rows, so reserve height for long keywords and notes.
            lines = sum(max(1, (sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
                                    for ch in line) + 95) // 96) for line in str(value).splitlines())
            row.set("ht", str(min(409, max(float(row.get("ht", 15)), lines * 17 + 6))))
            row.set("customHeight", "1")


def records(root, table, index, need_titles):
    @lru_cache(maxsize=128)
    def post_title(platform, post_id):
        row = index.execute("SELECT title FROM labels WHERE platform=? AND post_id=?", (platform, post_id)).fetchone()
        return row[0] if row else None

    for row in read_rows(root, table):
        pf = row.get("platform") or row["tool"].split("_", 1)[0]
        platform = PLATFORMS.get(pf, pf)
        if table == "posts":
            label = row.get("title") or (row.get("text") or "")[:90]
            if label and need_titles:
                index.execute("INSERT OR REPLACE INTO labels VALUES(?,?,?)", (pf, row["post_id"], label))
            yield (platform, "、".join(row.get("keywords") or []), row.get("title"), row.get("text"),
                   row.get("author_name"), local_time(row.get("published_at")), row.get("like_count"),
                   row.get("comment_count"), str(row["post_id"]), row.get("author_id"), row.get("url"),
                   "日期待核" if row.get("day_uncertain") else None)
        elif table == "comments":
            depth = row.get("depth", 0)
            level = f"{depth} 级回复" if depth else ("顶层返回" if row.get("relation_source") == "top_level_unspecified" else "顶层评论")
            yield (platform, post_title(pf, row["post_id"]), level, row.get("text"), row.get("author_name"),
                   local_time(row.get("created_at")), row.get("like_count"), str(row["post_id"]), str(row["comment_id"]),
                   row.get("parent_id"), row.get("root_id"))
        elif table == "authors":
            yield (platform, row.get("name"), row.get("bio"), row.get("followers"), row.get("following"),
                   row.get("likes_received"), row.get("post_count"), row.get("certification"),
                   row.get("public_id"), row.get("author_id"))
        else:
            detail, kind = row.get("detail") or {}, row["kind"]
            reached = detail.get("request_limit_reached" if kind == "search" else "limit_reached")
            issues = [detail[k] for k in ("error_code", "reason", "coverage_status") if detail.get(k)]
            if detail.get("unresolved_time"):
                issues.append(f"发布时间待核 {detail['unresolved_time']} 条")
            if detail.get("missing_id"):
                issues.append(f"缺少标识 {detail['missing_id']} 条")
            yield (platform, KINDS.get(kind, kind), str(row["target"]), STATES.get(row["state"], row["state"]),
                   (row.get("args") or {}).get("limit"), detail.get("authors" if kind == "author" else "unique_count"),
                   ("是" if reached else "否") if reached is not None else None, detail.get("known_reply_gap"),
                   row.get("receipt"), row.get("raw"), "；".join(issues) or None)


def worksheet_child(sheet, name, before):
    node = sheet.find(tag(name))
    if node is None:
        node = ET.Element(tag(name))
        pos = next((i for i, item in enumerate(sheet) if item.tag in {tag(k) for k in before}), len(sheet))
        sheet.insert(pos, node)
    return node


def display_height(fields, widths):
    """Excel does not autofit rows streamed into a preformatted worksheet."""
    lines = 1
    for value, width in zip(fields, widths):
        if not isinstance(value, str) or not value:
            continue
        wrapped = 0
        for line in value[:3000].splitlines():
            units = len(line) + sum(ord(char) > 255 for char in line)
            wrapped += max(1, (units + width - 1) // width)
        lines = max(lines, wrapped)
    return min(409, max(26, lines * 16 + 8))


def stream_details(archive, path, sheet, rows, count, width, posts):
    data = sheet.find(tag("sheetData"))
    sample = data.find(f"{tag('row')}[@r='4']")
    if sample is None:
        raise ValueError("明细模板缺少第 4 行样式")
    styles = {c.get("r")[:-1]: c.get("s", "0") for c in sample.findall(tag("c"))}
    cols = [chr(65 + i) for i in range(width)]
    widths = [max(2, int(float(col.get("width"))) - 2) for col in sheet.findall(f"{tag('cols')}/{tag('col')}")]
    for row in list(data):
        if int(row.get("r", 0)) >= 4:
            data.remove(row)
    last = 3 + count
    dim = worksheet_child(sheet, "dimension", ("sheetViews", "sheetFormatPr", "cols", "sheetData"))
    dim.set("ref", f"A1:{cols[-1]}{last}")
    auto = worksheet_child(sheet, "autoFilter", ("mergeCells", "hyperlinks", "pageMargins", "pageSetup", "drawing"))
    auto.set("ref", f"A3:{cols[-1]}{last}")
    views = worksheet_child(sheet, "sheetViews", ("sheetFormatPr", "cols", "sheetData"))
    view = views.find(tag("sheetView"))
    if view is None:
        view = ET.SubElement(views, tag("sheetView"), workbookViewId="0")
    pane = worksheet_child(view, "pane", ("selection",))
    pane.attrib.update(ySplit="3", topLeftCell="A4", activePane="bottomLeft", state="frozen")
    for selection in view.findall(tag("selection")):
        selection.set("pane", "bottomLeft")
    marker = ET.SubElement(data, "WORKBOOK_ROWS")
    prefix = sheet_xml(sheet).split(b"<WORKBOOK_ROWS />", 1)[0]
    # External links are added after the rows have streamed. Declare their relationship
    # namespace in the opening element now, before the matching links are known.
    if posts and b'xmlns:r="' not in prefix:
        prefix = prefix.replace(b"<worksheet ", f'<worksheet xmlns:r="{DOC}" '.encode(), 1)
    links = []
    with archive.open(path, "w", force_zip64=True) as stream:
        stream.write(prefix)
        for number in range(4, last + 1):
            try:
                fields = next(rows)
            except StopIteration:
                raise ValueError("明细行数与本轮汇总不符") from None
            if posts:
                url = fields[10]
                if fields[0] == PLATFORMS["xiaohongshu"]:
                    if url and xhs_note_url(fields[8], {"url": url}) == url:
                        links.append((number, url))
                    else:
                        fields = (*fields[:10], "缺少 xsec_token", *fields[11:])
                elif re.fullmatch(r"https://www\.douyin\.com/(?:video|note)/[0-9]+", url or ""):
                    links.append((number, url))
            cells = (cell_xml(col + str(number), styles.get(col, "0"), value) for col, value in zip(cols, fields))
            height = display_height(fields, widths)
            stream.write((f'<row r="{number}" ht="{height}" customHeight="1">' + "".join(cells) + "</row>").encode("utf-8"))
        if links:
            hyperlinks = worksheet_child(sheet, "hyperlinks", ("printOptions", "pageMargins", "pageSetup", "drawing"))
            for number, _ in links:
                ET.SubElement(hyperlinks, tag("hyperlink"), {"ref": f"K{number}", f"{{{DOC}}}id": f"link{number}"})
        stream.write(sheet_xml(sheet).split(b"<WORKBOOK_ROWS />", 1)[1])
    data.remove(marker)
    if links:
        rels = ET.Element("Relationships", xmlns=PKG)
        for number, url in links:
            ET.SubElement(rels, "Relationship", Id=f"link{number}", TargetMode="External",
                          Type=DOC + "/hyperlink", Target=url)
        folder, filename = posixpath.split(path)
        archive.writestr(f"{folder}/_rels/{filename}.rels", sheet_xml(rels))


def fill_workbook(src, out, root, plan, summary, note, index):
    book = ET.fromstring(src.read("xl/workbook.xml"))
    rels = ET.fromstring(src.read("xl/_rels/workbook.xml.rels"))
    types = ET.fromstring(src.read("[Content_Types].xml"))
    sheets = book.find(tag("sheets"))
    by_name = {s.get("name"): s for s in sheets}
    targets = {r.get("Id"): posixpath.normpath(posixpath.join("xl", r.get("Target"))).lstrip("/") for r in rels}
    paths = {name: targets[s.get(f"{{{DOC}}}id")] for name, s in by_name.items()}
    changed = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels", "[Content_Types].xml", *paths.values()}
    for part in src.infolist():
        if part.filename not in changed:
            out.writestr(part, src.read(part))
    overview = ET.fromstring(src.read(paths["概览"]))
    make_overview(overview, plan, summary, note)
    out.writestr(paths["概览"], sheet_xml(overview))
    next_id = max(int(s.get("sheetId")) for s in sheets) + 1
    for name, table, width in SHEETS:
        rows = records(root, table, index, summary["counts"]["comments"] > 0)
        total = sum(summary["tasks"].values()) if table == "tasks" else summary["counts"][table]
        # Excel allows 65,530 hyperlinks per sheet. Keeping all original-post links clickable
        # requires a smaller page for posts than the Excel row limit.
        capacity = min(65000, MAX_DATA_ROWS) if table == "posts" else MAX_DATA_ROWS
        pages = max(1, (total + capacity - 1) // capacity)
        for page in range(pages):
            sheet = ET.fromstring(src.read(paths[name]))
            path = paths[name]
            if page:
                path = f"xl/worksheets/sheet{next_id}.xml"
                rid = f"reportPage{next_id}"
                node = ET.Element(tag("sheet"), {"name": f"{name} {page + 1}", "sheetId": str(next_id), f"{{{DOC}}}id": rid})
                sheets.insert(list(sheets).index(by_name[name]) + page, node)
                ET.SubElement(rels, f"{{{PKG}}}Relationship", Id=rid, Type=DOC + "/worksheet", Target=path[3:])
                ET.SubElement(types, f"{{{CT}}}Override", PartName="/" + path,
                              ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
                next_id += 1
            enabled = summary["selected"].get(table, True)
            if not enabled:
                replace_cell(sheet, "A2", "本轮未勾选此项。")
            elif not total:
                replace_cell(sheet, "A2", "本轮暂未获得可展示的记录。可在任务记录中查看执行状态。")
            stream_details(out, path, sheet, rows, min(capacity, total - page * capacity), width, table == "posts")
        if next(rows, None) is not None:
            raise ValueError(f"{name}行数与本轮汇总不符")
    out.writestr("xl/workbook.xml", sheet_xml(book))
    for path, node, namespace in (("xl/_rels/workbook.xml.rels", rels, PKG), ("[Content_Types].xml", types, CT)):
        # OPC package readers expect the manifest and relationship elements in their default namespace.
        for element in node.iter():
            element.tag = element.tag.rsplit("}", 1)[-1]
        node.set("xmlns", namespace)
        out.writestr(path, sheet_xml(node))


def write_workbook(root: Path, plan: dict, summary: dict, *, note=None) -> Path:
    """Create a fresh snapshot, retaining the last workbook if this export fails."""
    root = Path(root)
    destination = root / "采集结果.xlsx"
    with tempfile.NamedTemporaryFile(dir=root, prefix=".report-", suffix=".xlsx", delete=False) as pending:
        temp_path = Path(pending.name)
    try:
        with ZipFile(TEMPLATE) as src, ZipFile(temp_path, "w", compression=ZIP_DEFLATED) as out, closing(sqlite3.connect("")) as index:
            index.execute("CREATE TABLE labels(platform TEXT,post_id TEXT,title TEXT, PRIMARY KEY(platform,post_id)) WITHOUT ROWID")
            fill_workbook(src, out, root, plan, summary, note, index)
        os.replace(temp_path, destination)
        return destination
    finally:
        temp_path.unlink(missing_ok=True)
