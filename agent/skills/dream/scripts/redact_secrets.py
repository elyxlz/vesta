#!/usr/bin/env python3
"""Scan events DB for secrets. Usage: redact_secrets.py [--delete]"""

import os
import re
import sqlite3
import sys

DB = os.path.expanduser("~/agent/data/events.db")

PATTERNS = [
    r"sk-[a-zA-Z0-9_-]{20,}",
    r"xox[bp]-[0-9A-Za-z-]+",
    r"gh[po]_[A-Za-z0-9]{36,}",
    r"glpat-[A-Za-z0-9_-]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    r"BEGIN [A-Z ]+ PRIVATE KEY",
    r"(?:password|secret|api[_-]?key)[\"': =]+[^ \"']{4,}",
    r"(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis)://[^ \"']+",
]
REGEX = re.compile("|".join(PATTERNS))


def main() -> int:
    if not os.path.isfile(DB):
        print(f"No database at {DB}")
        return 1

    delete = "--delete" in sys.argv[1:]
    conn = sqlite3.connect(DB)
    try:
        cursor = conn.execute("SELECT id, substr(data, 1, 200) FROM events")
        matches = [(row_id, snippet) for row_id, snippet in cursor if REGEX.search(snippet)]
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
