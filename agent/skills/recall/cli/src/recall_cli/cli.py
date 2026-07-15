#!/usr/bin/env python3
"""Full-text recall over the agent's whole conversation history (events.db).

Standalone, stdlib-only: the agent runs this as a subprocess, so it opens the db
directly rather than going through core. The query mirrors EventBus.search in
agent/core/events.py (same FTS5 table, same recency-boosted ranking); keep them
in step if that ranking ever changes.

Windowing (--snippet) is a CLI-only presentation concern computed in Python:
events_fts is an external-content table whose backing table has no text_content
column, so FTS5's own snippet() cannot re-read the source to build one.
"""

import argparse
import pathlib
import re
import sqlite3
import sys

DB_PATH = pathlib.Path.home() / "agent" / "data" / "events.db"
RECENCY_DECAY_RATE = 0.01
MAX_RESULT_CHARS = 50000
MAX_CONTENT_CHARS = 2000
SNIPPET_WINDOW_WORDS = 24
SNIPPET_ELLIPSIS = "…"

# FTS5 query operators, dropped when locating the matched term for --snippet windowing.
_FTS_OPERATORS = frozenset({"and", "or", "not", "near"})
_NON_WORD = re.compile(r"[^0-9a-z]")


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


def query_terms(query: str) -> list[str]:
    """The bare search terms of an FTS5 query: its alphanumeric runs, lowercased, with operators
    dropped. Used only to locate a match for windowing, so approximate parsing is fine."""
    return [token for token in re.findall(r"[0-9a-z]+", query.lower()) if token not in _FTS_OPERATORS]


def _matches(word: str, terms: list[str]) -> bool:
    cleaned = _NON_WORD.sub("", word.lower())
    return any(cleaned.startswith(term) for term in terms)


def window(content: str, query: str) -> str:
    """A short excerpt of content centered on the first word matching any query term, marked with
    SNIPPET_ELLIPSIS on each trimmed side. Falls back to the head of the message when no term can
    be located (e.g. an operator-only query)."""
    if not content:
        return content
    words = content.split()
    terms = query_terms(query)
    hit = next((i for i, candidate in enumerate(words) if _matches(candidate, terms)), None)
    if hit is None:
        head = words[: SNIPPET_WINDOW_WORDS * 2]
        suffix = f" {SNIPPET_ELLIPSIS}" if len(words) > len(head) else ""
        return " ".join(head) + suffix
    start = max(0, hit - SNIPPET_WINDOW_WORDS)
    end = min(len(words), hit + SNIPPET_WINDOW_WORDS + 1)
    prefix = f"{SNIPPET_ELLIPSIS} " if start > 0 else ""
    suffix = f" {SNIPPET_ELLIPSIS}" if end < len(words) else ""
    return prefix + " ".join(words[start:end]) + suffix


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
    parser.add_argument(
        "--snippet",
        action="store_true",
        help="Return a short windowed excerpt around each match instead of the full message "
        "(compresses large result sets; omit when you need full fidelity)",
    )
    args = parser.parse_args()

    try:
        results = search(DB_PATH, args.query, limit=args.limit)
    except sqlite3.OperationalError as e:
        print(f"Search error: {e}", file=sys.stderr)
        return 1
    if args.snippet:
        for r in results:
            r["content"] = window(r["content"], args.query)
    print(format_results(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
