#!/usr/bin/env python3
"""Full-text recall over the agent's whole conversation history (events.db).

Standalone, stdlib-only: the agent runs this as a subprocess, so it opens the db
directly rather than going through core. The query mirrors EventBus.search in
agent/core/events.py (same FTS5 table, same recency-boosted ranking); keep them
in step if that ranking ever changes.
"""

import argparse
import pathlib
import sqlite3
import sys

DB_PATH = pathlib.Path.home() / "agent" / "data" / "events.db"
RECENCY_DECAY_RATE = 0.01
MAX_RESULT_CHARS = 50000
MAX_CONTENT_CHARS = 2000


def search(db_path: pathlib.Path, query: str, *, limit: int) -> list[dict[str, str]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT e.ts, json_extract(e.data, '$.type') AS role, json_extract(e.data, '$.text') AS content,
                   f.rank / (1.0 + ? * max(julianday('now') - julianday(e.ts), 0)) AS score
            FROM events_fts f
            JOIN events e ON e.id = f.rowid
            WHERE events_fts MATCH ?
            ORDER BY score ASC
            LIMIT ?
            """,
            (RECENCY_DECAY_RATE, query, limit),
        ).fetchall()
    finally:
        conn.close()
    return [{"timestamp": r[0], "role": r[1], "content": r[2]} for r in rows]


def format_results(results: list[dict[str, str]]) -> str:
    if not results:
        return "No results found."
    lines: list[str] = []
    total = 0
    for r in results:
        content = r["content"]
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "..."
        line = f"[{r['timestamp']}] {r['role']}: {content}"
        if total + len(line) > MAX_RESULT_CHARS:
            lines.append(f"... ({len(results) - len(lines)} more results truncated)")
            break
        lines.append(line)
        total += len(line)
    return "\n\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall past conversations via full-text search.")
    parser.add_argument("query", help="FTS5 search query")
    parser.add_argument("--limit", type=int, default=20, help="Max results to return (default 20)")
    args = parser.parse_args()

    try:
        results = search(DB_PATH, args.query, limit=args.limit)
    except sqlite3.OperationalError as e:
        print(f"Search error: {e}", file=sys.stderr)
        return 1
    print(format_results(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
