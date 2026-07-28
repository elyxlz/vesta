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

# Structural false-positive filter, scoped to the sk- (hyphen) OpenAI pattern ONLY, because that is
# the one pattern whose body collides with English-word URL slugs: "sk-hynix-raises-full-year-
# guidance" (a SK Hynix news URL) matches sk-[a-zA-Z0-9_-]{20,} but is words, not a key. Other key
# families are deliberately NOT slug-checked: their bodies are hex/base62, not English words, and a
# short lowercase one (e.g. a Slack xoxb-1234-abcdef) would be wrongly skipped. A real sk- key
# always carries a long unbroken high-entropy run and/or uppercase, so it survives; a slug is short
# all-lowercase hyphen/underscore words. This generalises to slugs never seen before.
_SLUG_PREFIX = re.compile(r"^sk-")


def _looks_like_word_slug(token: str) -> bool:
    body, n = _SLUG_PREFIX.subn("", token)
    if n == 0:  # only sk- tokens are eligible; everything else is never treated as a slug
        return False
    if body != body.lower():  # a real sk- key carries uppercase/high-entropy; slugs are lowercase
        return False
    segs = [s for s in re.split(r"[-_]", body) if s]
    return len(segs) >= 2 and all(len(s) < 16 for s in segs)


def mask(match: re.Match[str]) -> str:
    """Replace a real hit with the placeholder; leave an already-scrubbed span untouched so the
    scan and scrub are both idempotent (a re-run never re-flags or mangles `password=[REDACTED]`)."""
    return match.group(0) if REDACTED in match.group(0) else REDACTED


# Payment-card PANs carry no fixed prefix to key a regex on, so this matches any candidate run and
# `_is_card` decides. A run of 13 to 19 digits may be split into groups by single spaces or hyphens
# (4111 1111 1111 1111, 3782-822463-10005). The lookarounds forbid a digit on either side so a
# longer numeric id is never sliced into a fake PAN.
CARD_CANDIDATE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
# Characters of surrounding text kept on each side of a hit, so the agent can judge it from context.
CONTEXT_CHARS = 40


def luhn_valid(digits: str) -> bool:
    """Standard Luhn checksum over a bare digit string, the payment-card industry's own check digit."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _has_card_iin(digits: str) -> bool:
    """True iff the leading digits fall in an assigned card-issuer range (ISO/IEC 7812 MII): 3
    (Amex/Diners/JCB), 4 (Visa), 5 (Mastercard/Maestro), 6 (Discover/UnionPay/Maestro), or a
    Mastercard 2-series (2221 to 2720). No card network issues outside those, so the runs this
    rejects (MII 0/1/7/8/9) are ids, not cards."""
    if digits[0] in "3456":
        return True
    return digits[0] == "2" and 2221 <= int(digits[:4]) <= 2720


def _is_card(candidate: str) -> bool:
    """A candidate run is a real PAN only when its stripped digits count 13 to 19, pass Luhn, AND open
    with an assigned card issuer prefix. Luhn alone flags ~1 in 10 non-card digit runs (a 13-digit
    timestamp can pass by chance); the IIN gate removes that class without dropping any real card."""
    digits = candidate.replace(" ", "").replace("-", "")
    return 13 <= len(digits) <= 19 and _has_card_iin(digits) and luhn_valid(digits)


def redact_cards(text: str) -> str:
    """Replace every PAN with the placeholder, leaving other digit runs (order numbers, timestamps,
    tracking ids) untouched. The `_is_card` check cannot live inside the combined REGEX, so this is
    its own pass, run after REGEX everywhere REGEX runs. `[REDACTED]` holds no digit run, so a re-run
    never re-flags or mangles one, matching the regex path's idempotency."""
    return CARD_CANDIDATE.sub(lambda m: REDACTED if _is_card(m.group(0)) else m.group(0), text)


type JsonValue = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None


def redact_json(value: JsonValue) -> JsonValue:
    """Recursively apply both redaction passes to every string inside a parsed JSON value. Redacting
    the decoded structure (not the serialized blob) guarantees the re-serialized event is still valid
    JSON: a raw text .sub can splice `[REDACTED]` across a `\"`/escape boundary and corrupt the blob,
    which then breaks the json_extract in the FTS resync and rolls back the whole scrub."""
    if isinstance(value, str):
        return redact_cards(REGEX.sub(mask, value))
    if isinstance(value, list):
        return [redact_json(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_json(v) for k, v in value.items()}
    return value


def _mask_context(window: str) -> str:
    """Mask both pattern hits and payment cards in a scan snippet, so reviewing a candidate never
    re-leaks the value back into a new event (the old redaction loop's self-reseeding)."""
    return redact_cards(REGEX.sub(mask, window)).replace("\n", " ")


def find_matches(text: str) -> list[str]:
    """Every secret in one string as a masked context snippet: the combined REGEX (already-redacted
    spans and news-slug false positives filtered out) plus the payment-card pass. Pure
    and DB-free, so the DB scan and the tests share exactly one detection path."""
    spans = [m.span() for m in REGEX.finditer(text) if REDACTED not in m.group(0) and not _looks_like_word_slug(m.group(0))]
    spans += [m.span() for m in CARD_CANDIDATE.finditer(text) if _is_card(m.group(0))]
    return [_mask_context(text[max(0, start - CONTEXT_CHARS) : end + CONTEXT_CHARS]) for start, end in spans]


def scan(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """Every hit as (event id, masked context snippet), regex patterns plus payment cards. The
    secret itself is replaced with [REDACTED] in the snippet, so reviewing candidates
    never re-leaks the value into a new event. Reports every match per event, not just the first, so
    a benign first hit can't mask a real secret later on. Scans the FULL event: secrets often sit
    deep inside long bash commands / tool payloads (an old PAT once survived weeks because
    substr(data,1,200) never saw it)."""
    matches = []
    for row_id, data in conn.execute("SELECT id, data FROM events"):
        if not data:
            continue
        matches.extend((row_id, snippet) for snippet in find_matches(data))
    return matches


def scrub(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Redact every hit in the given events in place, keeping their context and events_fts. Driven by
    the same patterns and keyed by id, so the caller never has to pass (and thereby re-leak) the literal."""
    changed: dict[int, str] = {}
    for row_id in ids:
        row = conn.execute("SELECT data FROM events WHERE id = ?", (row_id,)).fetchone()
        if row is None or not row[0]:
            continue
        try:
            obj = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            # Non-JSON payload: fall back to a raw text sub (nothing to keep valid).
            new_data = redact_cards(REGEX.sub(mask, row[0]))
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
