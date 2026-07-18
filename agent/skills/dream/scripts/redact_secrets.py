#!/usr/bin/env python3
"""Scan the events DB for secrets, then scrub the real leaks in place by event id.
Usage: redact_secrets.py            # scan, printing each hit with the value masked
       redact_secrets.py --scrub ID [ID ...]   # redact every secret in those events
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

DB = Path("~/agent/data/events.db").expanduser()
REDACTED = "[REDACTED]"
# Event types indexed by events_fts (mirrors the triggers in core/events.py). The schema has
# insert/delete triggers only, so an in-place UPDATE must resync the index itself: otherwise the
# old text (with the secret) stays searchable and a later delete corrupts the external-content index.
FTS_TYPES = ("user", "assistant", "chat")

PATTERNS = [
    r"sk-[a-zA-Z0-9_-]{20,}",
    # Stripe secret + restricted keys use an UNDERSCORE (sk_live_ / sk_test_ / rk_live_ / rk_test_),
    # so the sk- (hyphen) pattern above never matched them. Publishable pk_ keys are not secret and
    # are deliberately excluded.
    r"[sr]k_(?:live|test)_[0-9a-zA-Z]{20,}",
    r"xox[bp]-[0-9A-Za-z-]+",
    r"gh[posr]_[A-Za-z0-9]{36,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"glpat-[A-Za-z0-9_-]{20,}",
    r"(?-i:AKIA[0-9A-Z]{16})",  # case-sensitive: real AWS keys are uppercase. Under the outer
    # IGNORECASE, a plain AKIA matches "akia...." runs inside base64 blobs (reasoning-block
    # signatures, media keys), a recurring false positive that buries the real matches.
    r"PMAK-[A-Za-z0-9-]{20,}",
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    r"BEGIN [A-Z ]+ PRIVATE KEY",
    # A real separator char (: = or a quote) is mandatory, so benign prose like "password reuse"
    # (bare space between word and value) never matches; spaces around it are tolerated so
    # space-padded assignments still hit (password = "x", YAML password: "x"). The \\? bits absorb
    # the backslash JSON puts before an escaped quote, since the scan runs over the JSON `data` blob.
    r"(?:password|secret|api[_-]?key)[ ]*\\?[\"':=]+[ ]*\\?[\"']?[^ \"'\\]{4,}",
    r"(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis)://[^ \"']+",
]
REGEX = re.compile("|".join(PATTERNS), re.IGNORECASE)

# Structural false-positive filter for news/URL slugs. The sk-[a-zA-Z0-9_-]{20,} pattern also
# matches hyphenated headline slugs that begin sk- (e.g. "sk-hynix-raises-full-year-guidance" from
# a SK Hynix news URL), which are not secrets. Every real key we scan for carries a long unbroken
# high-entropy run (OpenAI 40+ base62 body, gh/glpat 20-36+, AKIA 16, JWT), while a slug is short
# hyphen/underscore-separated lowercase words. So: strip a key-ish prefix, and if the remainder is
# all-lowercase with >=2 segments none >=16 chars, it is a slug. This cannot mask a real key (they
# always have a >=16 unbroken run and/or uppercase) and generalises to slugs never seen before.
_SLUG_PREFIX = re.compile(r"^(sk|gh[posr]|glpat|xox[bp]|pmak|akia)[-_]", re.IGNORECASE)


def _looks_like_word_slug(token: str) -> bool:
    body, n = _SLUG_PREFIX.subn("", token)
    if n == 0:  # not key-prefixed (password/db-url matches): never treat as a slug
        return False
    if body != body.lower():  # real keys carry uppercase/high-entropy; slugs are lowercase
        return False
    segs = [s for s in re.split(r"[-_]", body) if s]
    return len(segs) >= 2 and all(len(s) < 16 for s in segs)


def mask(match: re.Match[str]) -> str:
    """Replace a real hit with the placeholder; leave an already-scrubbed span untouched so the
    scan and scrub are both idempotent (a re-run never re-flags or mangles `password=[REDACTED]`)."""
    return match.group(0) if REDACTED in match.group(0) else REDACTED


type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def redact_json(value: JsonValue) -> JsonValue:
    """Recursively apply the mask regex to every string inside a parsed JSON value. Redacting the
    decoded structure (not the serialized blob) guarantees the re-serialized event is still valid
    JSON: a raw text .sub can splice `[REDACTED]` across a `\"`/escape boundary and corrupt the blob,
    which then breaks the json_extract in the FTS resync and rolls back the whole scrub."""
    if isinstance(value, str):
        return REGEX.sub(mask, value)
    if isinstance(value, list):
        return [redact_json(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_json(v) for k, v in value.items()}
    return value


def scan(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """Every pattern hit as (event id, masked context snippet). The secret itself is replaced with
    [REDACTED] in the snippet, so reviewing candidates never re-leaks the value into a new event
    (the old redaction loop's self-reseeding). Reports every match per event, not just the first,
    so a benign first hit can't mask a real secret later on. Scans the FULL event: secrets often sit
    deep inside long bash commands / tool payloads (an old PAT once survived weeks because
    substr(data,1,200) never saw it)."""
    matches = []
    for row_id, data in conn.execute("SELECT id, data FROM events"):
        if not data:
            continue
        for m in REGEX.finditer(data):
            if REDACTED in m.group(0):
                continue
            if _looks_like_word_slug(m.group(0)):
                continue  # news/URL slug (hyphenated words), not a secret
            window = data[max(0, m.start() - 40) : m.end() + 40]
            matches.append((row_id, REGEX.sub(mask, window).replace("\n", " ")))
    return matches


def scrub(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Redact every pattern hit in the given events in place, keeping their context and events_fts.
    Regex-driven and keyed by id, so the caller never has to pass (and thereby re-leak) the literal."""
    changed: dict[int, str] = {}
    for row_id in ids:
        row = conn.execute("SELECT data FROM events WHERE id = ?", (row_id,)).fetchone()
        if row is None or not row[0]:
            continue
        try:
            obj = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            # Non-JSON payload: fall back to a raw text sub (nothing to keep valid).
            new_data = REGEX.sub(mask, row[0])
            if new_data != row[0]:
                changed[row_id] = new_data
            continue
        new_obj = redact_json(obj)
        if new_obj != obj:
            # Re-serialize only when a real redaction changed the structure, so events with no
            # secret are never rewritten (a reformat-only diff would rewrite every event). Match
            # events.py's json.dumps(event) so a scrubbed blob keeps the fleet's byte representation.
            changed[row_id] = json.dumps(new_obj)
    if not changed:
        return 0
    changed_ids = list(changed)
    id_marks = ",".join("?" * len(changed_ids))
    type_marks = ",".join("?" * len(FTS_TYPES))
    fts_where = f"id IN ({id_marks}) AND json_extract(data, '$.type') IN ({type_marks}) AND json_extract(data, '$.text') IS NOT NULL"
    conn.execute(
        "INSERT INTO events_fts(events_fts, rowid, text_content) "
        f"SELECT 'delete', id, json_extract(data, '$.text') FROM events WHERE {fts_where}",
        (*changed_ids, *FTS_TYPES),
    )
    for row_id, new_data in changed.items():
        conn.execute("UPDATE events SET data = ? WHERE id = ?", (new_data, row_id))
    conn.execute(
        f"INSERT INTO events_fts(rowid, text_content) SELECT id, json_extract(data, '$.text') FROM events WHERE {fts_where}",
        (*changed_ids, *FTS_TYPES),
    )
    conn.commit()
    return len(changed)


def main() -> int:
    if not DB.is_file():
        print(f"No database at {DB}")
        return 1

    args = sys.argv[1:]
    conn = sqlite3.connect(DB)
    try:
        if args[:1] == ["--scrub"]:
            scrubbed = scrub(conn, [int(arg) for arg in args[1:]])
            print(f"Scrubbed secrets in {scrubbed} event(s) in place.")
            return 0

        matches = scan(conn)
        if not matches:
            print("No secrets found.")
            return 0

        ids = sorted({row_id for row_id, _ in matches})
        print(f"Found {len(ids)} event(s) with potential secrets (value masked below).")
        print("Review the context, then redact the real leaks: redact_secrets.sh --scrub <id> <id> ...")
        # Never cap this list: matches arrive in rowid order, so any cap hides the newest events' leaks.
        for row_id, snippet in matches:
            print(f"{row_id}|{snippet}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
