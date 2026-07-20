"""CLI commands: send and history."""

import argparse
import asyncio
import json
import pathlib as pl
import sqlite3
import sys

from app_chat_cli.bubblelint import bubble_lint_reason
from app_chat_cli.store import Store, store_path


def cmd_send(args: argparse.Namespace) -> None:
    message = args.message

    if not getattr(args, "longform", False):
        reason = bubble_lint_reason(message)
        if reason:
            print(json.dumps({"error": reason}))
            sys.exit(1)

    sock_path = pl.Path(args.socket or (pl.Path.home() / ".app-chat" / "app-chat.sock"))

    if not sock_path.exists():
        print(json.dumps({"error": f"daemon not running (no socket at {sock_path})"}))
        sys.exit(1)

    result = asyncio.run(_send_via_socket(sock_path, message))
    print(json.dumps(result))
    if "error" in result:
        sys.exit(1)


async def _send_via_socket(sock_path: pl.Path, message: str) -> dict[str, object]:
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        request = json.dumps({"command": "send", "message": message})
        writer.write(request.encode())
        writer.write_eof()
        data = await asyncio.wait_for(reader.read(65536), timeout=10.0)
        writer.close()
        await writer.wait_closed()
        return json.loads(data.decode())
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def cmd_history(args: argparse.Namespace) -> None:
    data_dir = pl.Path(args.data_dir or (pl.Path.home() / ".app-chat"))
    store = Store(store_path(data_dir))
    try:
        if args.search:
            events = store.search(args.search, limit=args.limit)
        else:
            events, _ = store.page(limit=args.limit)
    except sqlite3.OperationalError as exc:
        print(json.dumps({"error": f"invalid search query: {exc}"}))
        sys.exit(1)
    finally:
        store.close()
    results = [{"timestamp": e["ts"], "role": e["type"], "content": e["text"]} for e in events]
    print(json.dumps(results, indent=2))
