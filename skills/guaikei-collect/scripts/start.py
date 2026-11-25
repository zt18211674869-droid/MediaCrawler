"""Open the collection form and publish its confirmed settings directly to a new queue."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from qa import read_prefill, serve
from run import initialize_from_config


def start(root, prefill, timeout, open_browser, available_tools):
    if root.exists():
        raise ValueError("本轮输出目录已存在，请为新一轮选择新的目录。")
    queued = None

    def enqueue(config):
        nonlocal queued
        queued = initialize_from_config(root, config, available_tools=available_tools)

    serve(prefill, timeout, open_browser, on_confirm=enqueue)
    return {"status": "queued", **queued} if queued is not None else {"status": "cancelled"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="本轮新建的本地运行目录")
    parser.add_argument("--prefill", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--tools", help="当前已发现的怪 K 工具短名，使用半角逗号分隔")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("等待时间至少为 1 秒")
    try:
        available = set(args.tools.split(",")) if args.tools is not None else None
        result = start(args.run.resolve(), read_prefill(args.prefill), args.timeout, not args.no_open, available)
        sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
    except (ValueError, OSError, sqlite3.Error) as error:
        sys.stderr.buffer.write((str(error) + "\n").encode("utf-8"))
        return 2
    except KeyboardInterrupt:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
