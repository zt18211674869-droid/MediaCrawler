"""Collect one confirmed configuration through a local browser form."""

import argparse
import json
import os
import secrets
import sys
import time
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import NamedTemporaryFile


FORM = Path(__file__).resolve().parents[1] / "assets" / "configure.html"
BODY_LIMIT = 128 * 1024


def read_prefill(path):
    if path is None:
        return {}
    with path.open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("预填配置应为 JSON 对象")
    return value


def write_new_config(path, config):
    # Publish a complete UTF-8 file; concurrent writers cannot replace an existing path.
    temp = NamedTemporaryFile(dir=path.parent, delete=False)
    temporary = Path(temp.name)
    try:
        with temp:
            temp.write((json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        if os.name == "nt":
            os.rename(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def serve(prefill, timeout, open_browser, *, on_confirm=None):
    from plan import build_plan

    # The secret path prevents unrelated local pages from completing this form.
    prefix = "/" + secrets.token_urlsafe(24) + "/"
    form = FORM.read_bytes()
    state = {"done": False, "config": None}

    class LocalServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            # Browsers can open a speculative connection without sending headers.
            connection.settimeout(min(2, timeout))
            return connection, address

    class FormHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, data, media_type):
            self.send_response(status)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (ConnectionResetError, BrokenPipeError):
                pass

        def send_json(self, status, value):
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.reply(status, data, "application/json; charset=utf-8")

        def do_GET(self):
            if self.path == prefix:
                self.reply(200, form, "text/html; charset=utf-8")
            elif self.path == prefix + "prefill":
                self.send_json(200, prefill)
            else:
                self.send_error(404)

        def do_POST(self):
            if self.headers.get("Origin") not in (None, origin):
                self.send_error(403)
                return
            if self.path == prefix + "cancel":
                state["done"] = True
                self.send_json(200, {"ok": True})
                return
            if self.path != prefix + "confirm":
                self.send_error(404)
                return
            if self.headers.get_content_type() != "application/json":
                self.send_error(415)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= BODY_LIMIT:
                    raise ValueError("配置的大小超出可接受范围")
                config = json.loads(self.rfile.read(size).decode("utf-8"))
                if not isinstance(config, dict):
                    raise ValueError("配置应为 JSON 对象")
                build_plan(config)
            except (ValueError, TypeError, KeyError, OSError) as exc:
                self.send_json(400, {"error": str(exc)})
                return
            # A successful acknowledgment lets the browser dismiss the only form.
            # Publish to the host first so a failed write cannot look confirmed.
            try:
                if on_confirm is not None:
                    on_confirm(config)
            except FileExistsError:
                self.send_json(409, {"error": "本轮输出已存在，请关闭弹窗并从当前 Skill 重新发起。"})
                return
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            except Exception as exc:
                print(f"配置交接失败：{exc}", file=sys.stderr, flush=True)
                self.send_json(500, {"error": "Skill 未接收配置，请检查本机运行目录后重试。"})
                return
            state.update(done=True, config=config)
            self.send_json(200, {"ok": True})

    with LocalServer(("127.0.0.1", 0), FormHandler) as server:
        server.timeout = 0.5
        origin = "http://127.0.0.1:" + str(server.server_port)
        url = origin + prefix
        print(url, file=sys.stderr, flush=True)
        if open_browser:
            webbrowser.open(url, new=1)
        deadline = time.monotonic() + timeout
        while not state["done"] and time.monotonic() < deadline:
            server.handle_request()
    return state["config"]


def main():
    parser = argparse.ArgumentParser(description="本地采集配置弹窗。确认后将配置 JSON 输出到标准输出。")
    parser.add_argument("--prefill", type=Path, help="用于预填的 JSON 文件，可只包含部分字段")
    parser.add_argument("--output", type=Path, help="同时保存为新的 UTF-8 JSON 文件，父目录须已存在")
    parser.add_argument("--timeout", type=int, default=600, help="等待确认的秒数，默认 600")
    parser.add_argument("--no-open", action="store_true", help="只在标准错误显示本机地址")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("等待时间至少为 1 秒")
    if args.output is not None:
        if os.path.lexists(args.output):
            parser.error("输出文件已存在，请指定新文件")
        if not args.output.parent.is_dir():
            parser.error("输出文件的父目录不存在")
    try:
        publish = partial(write_new_config, args.output) if args.output is not None else None
        config = serve(read_prefill(args.prefill), args.timeout, not args.no_open, on_confirm=publish)
    except (ValueError, OSError) as exc:
        parser.exit(2, str(exc) + "\n")
    except KeyboardInterrupt:
        return 1
    if config is None:
        print("配置已取消或等待超时。", file=sys.stderr)
        return 1
    print(json.dumps(config, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
