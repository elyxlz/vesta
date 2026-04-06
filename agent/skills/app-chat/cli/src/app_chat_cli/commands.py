"""CLI commands: send and history."""

import asyncio
import json
import pathlib as pl
import sqlite3
import sys

RECENCY_DECAY_RATE = 0.01


def cmd_send(args: object) -> None:
    message = args.message
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
        return json.loads(data.decode())
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def cmd_history(args: object) -> None:
    query = args.search
    limit = args.limit
    db_path = pl.Path(args.db or (pl.Path.home() / "vesta" / "data" / "events.db"))

    if not db_path.exists():
        print(json.dumps({"error": f"events.db not found at {db_path}"}))
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    try:
        if query:
            rows = conn.execute(
                """
                SELECT e.ts, json_extract(e.data, '$.type') AS role, json_extract(e.data, '$.text') AS content
                FROM events_fts f
                JOIN events e ON e.id = f.rowid
                WHERE events_fts MATCH ?
                ORDER BY f.rank / (1.0 + ? * max(julianday('now') - julianday(e.ts), 0)) ASC
                LIMIT ?
                """,
                (query, RECENCY_DECAY_RATE, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT ts, json_extract(data, '$.type') AS role, json_extract(data, '$.text') AS content
                FROM events
                WHERE json_extract(data, '$.type') IN ('user', 'assistant', 'chat')
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            rows = list(reversed(rows))

        results = [{"timestamp": r[0], "role": r[1], "content": r[2]} for r in rows]
        print(json.dumps(results, indent=2))
    finally:
        conn.close()
