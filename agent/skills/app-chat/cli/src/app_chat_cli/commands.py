"""CLI commands: send, history, and import."""

import argparse
import asyncio
import json
import os
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


def _default_events_db() -> pl.Path:
    """Core's events.db on box: `$AGENT_DIR/data/events.db` (default `~/agent`), mirroring config.data_dir."""
    agent_dir = os.environ.get("AGENT_DIR")
    base = pl.Path(agent_dir).expanduser() if agent_dir else pl.Path.home() / "agent"
    return base / "data" / "events.db"


def cmd_import(args: argparse.Namespace) -> None:
    """Copy channel=app-chat conversation rows from core's events.db into the skill store, preserving ids
    and bumping the sequence above them (D3). Idempotent (INSERT OR IGNORE); the store's AFTER INSERT
    trigger indexes each imported row so `history --search` covers old conversations."""
    events_db = pl.Path(args.events_db) if args.events_db else _default_events_db()
    data_dir = pl.Path(args.data_dir or (pl.Path.home() / ".app-chat"))
    if not events_db.exists():
        print(json.dumps({"status": "no_events_db", "path": str(events_db)}))
        return
    src = sqlite3.connect(str(events_db), timeout=30)
    try:
        rows = src.execute("SELECT id, ts, data FROM events WHERE json_extract(data, '$.type') IN ('user', 'chat') ORDER BY id ASC").fetchall()
    finally:
        src.close()
    store = Store(store_path(data_dir))
    try:
        count, max_id = store.import_rows(rows)
        if max_id:
            store.bump_sequence_above(max_id)
    finally:
        store.close()
    print(json.dumps({"status": "imported", "rows": count, "max_id": max_id}))
