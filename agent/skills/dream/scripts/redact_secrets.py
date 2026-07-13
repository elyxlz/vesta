#!/usr/bin/env python3
"""Scan events DB for secrets and scrub known-leaked literals. Usage: redact_secrets.py [--delete]"""

import os
import re
import sqlite3
import sys

DB = os.path.expanduser("~/agent/data/events.db")
# One known-leaked literal per line (# comments allowed). Lives in the gitignored data dir so the
# literals never reach tracked source or the upstream snapshot. Scrubbed in place on every run:
# a leaked secret re-seeds itself (the agent reasons about it in later events), so a one-time
# delete never converges; the standing scrub does.
KNOWN_FILE = os.path.expanduser("~/agent/data/redact_known.txt")
REDACTED = "[REDACTED]"
# Event types indexed by events_fts (mirrors the triggers in core/events.py). The schema has
# insert/delete triggers only, so an in-place UPDATE must resync the index itself: otherwise the
# old text (with the secret) stays searchable and a later delete corrupts the external-content index.
FTS_TYPES = ("user", "assistant", "chat")

PATTERNS = [
    r"sk-[a-zA-Z0-9_-]{20,}",
    r"xox[bp]-[0-9A-Za-z-]+",
    r"gh[posr]_[A-Za-z0-9]{36,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"glpat-[A-Za-z0-9_-]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"PMAK-[A-Za-z0-9-]{20,}",
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    r"BEGIN [A-Z ]+ PRIVATE KEY",
    r"(?:password|secret|api[_-]?key)[\"': =]+[^ \"']{4,}",
    r"(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis)://[^ \"']+",
]
REGEX = re.compile("|".join(PATTERNS), re.IGNORECASE)


def read_known() -> list[str]:
    if not os.path.isfile(KNOWN_FILE):
        return []
    with open(KNOWN_FILE) as f:
        return [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]


def scrub_known(conn: sqlite3.Connection) -> int:
    """Replace every occurrence of each known-leaked literal in place, keeping events_fts in sync."""
    scrubbed_ids: set[int] = set()
    type_marks = ",".join("?" * len(FTS_TYPES))
    for literal in read_known():
        ids = [row[0] for row in conn.execute("SELECT id FROM events WHERE instr(data, ?) > 0", (literal,))]
        if not ids:
            continue
        id_marks = ",".join("?" * len(ids))
        fts_where = f"id IN ({id_marks}) AND json_extract(data, '$.type') IN ({type_marks}) AND json_extract(data, '$.text') IS NOT NULL"
        conn.execute(
            "INSERT INTO events_fts(events_fts, rowid, text_content) "
            f"SELECT 'delete', id, json_extract(data, '$.text') FROM events WHERE {fts_where}",
            (*ids, *FTS_TYPES),
        )
        conn.execute(f"UPDATE events SET data = REPLACE(data, ?, ?) WHERE id IN ({id_marks})", (literal, REDACTED, *ids))
        conn.execute(
            f"INSERT INTO events_fts(rowid, text_content) SELECT id, json_extract(data, '$.text') FROM events WHERE {fts_where}",
            (*ids, *FTS_TYPES),
        )
        scrubbed_ids.update(ids)
    conn.commit()
    return len(scrubbed_ids)


def scan(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """All pattern hits as (event id, context snippet): every match per event, not just the first,
    so a benign first hit can't mask a real secret later in the same event. Scans the FULL event:
    secrets often sit deep inside long bash commands / tool payloads (an old PAT once survived
    weeks because substr(data,1,200) never saw it). Already-scrubbed values are skipped."""
    matches = []
    for row_id, data in conn.execute("SELECT id, data FROM events"):
        if not data:
            continue
        for m in REGEX.finditer(data):
            if REDACTED in m.group(0):
                continue
            start = max(0, m.start() - 40)
            snippet = data[start : m.end() + 40].replace("\n", " ")
            matches.append((row_id, snippet))
    return matches


def main() -> int:
    if not os.path.isfile(DB):
        print(f"No database at {DB}")
        return 1

    delete = "--delete" in sys.argv[1:]
    conn = sqlite3.connect(DB)
    try:
        scrubbed = scrub_known(conn)
        if scrubbed:
            print(f"Scrubbed {scrubbed} events containing known-leaked literals in place.")
        matches = scan(conn)
    finally:
        conn.close()

    if not matches:
        print("No secrets found.")
        return 0

    ids = sorted({row_id for row_id, _ in matches})
    print(f"Found {len(ids)} events with potential secrets:")
    for row_id, snippet in matches[:20]:
        print(f"{row_id}|{snippet}")

    if delete:
        conn = sqlite3.connect(DB)
        try:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM events WHERE id IN ({placeholders})", ids)
            conn.commit()
        finally:
            conn.close()
        print(f"Deleted {len(ids)} events.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
