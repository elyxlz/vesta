"""CLI commands: send, history, import, and the attachments disk-management verbs."""

import argparse
import asyncio
import json
import os
import pathlib as pl
import re
import sqlite3
import sys
import typing as tp

from app_chat_cli import attachments
from app_chat_cli.bubblelint import bubble_lint_reason
from app_chat_cli.store import Store, store_path


def _fail(payload: dict[str, object]) -> None:
    """The one failure printer: the payload goes to stderr so stdout carries only success output."""
    print(json.dumps(payload), file=sys.stderr)
    sys.exit(1)


_DEFAULT_GAP_SECS = 2.5


def _collect_bubbles(message: list[str] | None, longform: bool) -> list[str]:
    """The reply's bubbles, in order. A lone `-` reads the whole reply from stdin, one bubble per
    blank-line-separated paragraph (one bubble in all under --longform), so a reply with
    apostrophes, quotes or newlines rides a quoted heredoc. Blank bubbles are dropped so a stray
    empty -m never sends an empty message."""
    raw = message or []
    if raw == ["-"]:
        body = sys.stdin.read()
        raw = [paragraph.strip("\r\n") for paragraph in ([body] if longform else re.split(r"\n\s*\n", body))]
    return [bubble for bubble in raw if bubble.strip()]


def cmd_send(args: argparse.Namespace) -> None:
    bubbles = _collect_bubbles(args.message, args.longform)
    # Absolute paths cross the socket: the daemon's cwd is wherever `daemon start` ran, never the
    # sender's, so a relative --attach would resolve against the wrong directory.
    attach: list[str] = [str(pl.Path(path).expanduser().resolve()) for path in args.attach or []]
    if not bubbles and not attach:
        _fail({"error": "--message is empty (pass '-' and a <<'MSG' heredoc to read the body from stdin, or --attach a file)"})

    if not args.longform:
        # Lint every bubble before sending any of it, so a malformed bubble never leaves a
        # half-sent waterfall behind.
        for bubble in bubbles:
            reason = bubble_lint_reason(bubble)
            if reason:
                _fail({"error": reason})

    sock_path = pl.Path(args.socket or (pl.Path.home() / ".app-chat" / "app-chat.sock"))

    if not sock_path.exists():
        _fail({"error": f"daemon not running (no socket at {sock_path})"})

    gap = _DEFAULT_GAP_SECS if args.gap is None else args.gap
    result = asyncio.run(_send_bubbles(sock_path, bubbles, attach, gap))
    if "error" in result:
        _fail(result)
    print(json.dumps(result))


async def _send_bubbles(sock_path: pl.Path, bubbles: list[str], attach: list[str], gap: float) -> dict[str, object]:
    """Send a reply as one paced, interruptible stream: bubbles go out in order with `gap` seconds
    between them, the attachments ride the last one, and the first refusal while the user is talking
    stops the rest (the daemon re-wakes the agent once the floor clears)."""
    outbound = bubbles or [""]  # an attachment-only reply is one empty-text bubble carrying the file
    sent: list[dict[str, object]] = []
    for index, bubble in enumerate(outbound):
        last = index == len(outbound) - 1
        result = await _send_via_socket(sock_path, bubble, attach if last else [])
        if "user_speaking" in result:
            return {"ok": True, "sent": sent, "stopped_for_user": True}
        if "error" in result:
            return result
        sent.append({"id": result["id"], "message": bubble})
        if not last:
            await asyncio.sleep(gap)
    return {"ok": True, "sent": sent, "stopped_for_user": False}


async def _send_via_socket(sock_path: pl.Path, message: str, attach: list[str]) -> dict[str, object]:
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        request = json.dumps({"command": "send", "message": message, "attach": attach})
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
        _fail({"error": f"invalid search query: {exc}"})
    finally:
        store.close()
    results = [{"timestamp": e["ts"], "role": e["type"], "content": e["text"]} for e in events]
    print(json.dumps(results, indent=2))


class _ListedAttachment(tp.TypedDict):
    id: str
    name: str
    mime: str
    size: int
    ts: str | None
    direction: str | None
    removed: bool


def _attachments_root(args: argparse.Namespace) -> pl.Path:
    return attachments.attachments_root(pl.Path(args.data_dir or (pl.Path.home() / ".app-chat")))


def cmd_attachments_list(args: argparse.Namespace) -> None:
    """Every finalized attachment with its size, joined to the event that references it (ts + whether it
    was received from the user or sent by the agent). Largest first by default; count and total_bytes
    describe the filtered set even when --limit trims the printed array."""
    root = _attachments_root(args)
    store = Store(store_path(root.parent))
    rows: list[_ListedAttachment] = []
    try:
        references = store.attachment_references()
        for directory in sorted(root.iterdir()) if root.exists() else []:
            meta = attachments.read_meta(root, directory.name)
            if meta is None:
                continue  # staging sessions have nothing to list yet
            reference = references[meta["id"]] if meta["id"] in references else None
            rows.append(
                {
                    "id": meta["id"],
                    "name": meta["name"],
                    "mime": meta["mime"],
                    "size": meta["size"],
                    "ts": reference[0] if reference is not None else None,
                    "direction": (("received" if reference[1] == "user" else "sent") if reference is not None else None),
                    "removed": attachments.is_removed(root, meta["id"]),
                }
            )
    finally:
        store.close()
    if args.min_size is not None:
        rows = [row for row in rows if row["size"] >= args.min_size]
    if args.sort == "date":
        rows.sort(key=lambda row: row["ts"] if row["ts"] is not None else "", reverse=True)
    else:
        rows.sort(key=lambda row: row["size"], reverse=True)
    total = sum(row["size"] for row in rows if not row["removed"])
    listed = rows[: args.limit] if args.limit is not None else rows
    print(json.dumps({"attachments": listed, "count": len(rows), "total_bytes": total}))


def cmd_attachments_rm(args: argparse.Namespace) -> None:
    """Free the bytes of one or more attachments, keeping each meta so chat history renders a clean
    "no longer available" tile instead of a broken bubble. All ids are validated before any blob is
    touched, so a typo never leaves a half-applied removal behind an error."""
    root = _attachments_root(args)
    for attachment_id in args.ids:
        if attachments.read_meta(root, attachment_id) is None:
            _fail({"error": f"unknown attachment: {attachment_id}"})
    freed = 0
    for attachment_id in args.ids:
        freed += attachments.remove_blob(root, attachment_id)
    print(json.dumps({"removed": args.ids, "freed_bytes": freed}))


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
