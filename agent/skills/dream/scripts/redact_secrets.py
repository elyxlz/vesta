#!/usr/bin/env python3
"""Scan the events DB for secrets, then scrub the real leaks in place by event id.
Usage: redact_secrets.py            # scan, printing each hit with the value masked
       redact_secrets.py --show ID  # print one event's full data with every detected secret masked
       redact_secrets.py --scrub ID [ID ...]   # redact every secret in those events
       redact_secrets.py --scrub-literal 'VALUE'   # redact one known value the scanner can't detect
"""

import json
import re
import sqlite3
import sys
import typing as tp
from pathlib import Path

DB = Path("~/agent/data/events.db").expanduser()
REDACTED = "[REDACTED]"
# The shortest value --scrub-literal accepts: the rewrite is DB-wide, so a tiny literal ("a", "key")
# would splice the placeholder through unrelated text across the entire history.
MIN_LITERAL_LEN = 6
# The rows events_fts indexes, and the column each is indexed by (mirrors the triggers in
# core/events.py): conversational events by $.text, non-core notifications by $.summary. The
# schema has insert/delete triggers only, so an in-place UPDATE must resync the index itself:
# otherwise the old text (with the secret) stays searchable and a later delete corrupts the
# external-content index.
FTS_INDEXED = (
    "((json_extract(data, '$.type') IN ('user', 'assistant', 'chat') AND json_extract(data, '$.text') IS NOT NULL)"
    " OR (json_extract(data, '$.type') = 'notification'"
    " AND COALESCE(json_extract(data, '$.source'), '') <> 'core'"
    " AND json_extract(data, '$.summary') IS NOT NULL))"
)
FTS_TEXT = "COALESCE(json_extract(data, '$.text'), json_extract(data, '$.summary'))"

PATTERNS = [
    r"sk-[a-zA-Z0-9_-]{20,}",
    # Stripe secret + restricted keys use an UNDERSCORE (sk_live_ / sk_test_ / rk_live_ / rk_test_),
    # so the sk- (hyphen) pattern above never matched them. Publishable pk_ keys are not secret and
    # are deliberately excluded.
    r"[sr]k_(?:live|test)_[0-9a-zA-Z]{20,}",
    r"xox[bp]-[0-9A-Za-z-]+",
    # GitHub App installation tokens are ghs_<installation-id>_<jwt> (the format `upstream-pr
    # --token-only` hands out), so the class allows underscores and dots: without them the match
    # dies at the first underscore and a truncated copy escapes entirely. The prefix class carries
    # all five token families (p personal, o OAuth, u user-to-server, s server-to-server, r
    # refresh); a prefix left out means that whole token type passes the sweep.
    r"gh[posru]_[A-Za-z0-9_.\-]{36,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"glpat-[A-Za-z0-9_-]{20,}",
    r"(?-i:AKIA[0-9A-Z]{16})",  # case-sensitive: real AWS keys are uppercase. Under the outer
    # IGNORECASE, a plain AKIA matches "akia...." runs inside base64 blobs (reasoning-block
    # signatures, media keys), a recurring false positive that buries the real matches.
    r"PMAK-[A-Za-z0-9-]{20,}",
    # Fixed vendor prefixes, case-anchored for the same reason AKIA is: under the outer IGNORECASE a
    # short lowercase prefix matches its own letters inside base64url runs and buries real rows.
    # This list only covers vendors someone has enumerated, so a clean scan means "no known-shape
    # secret", never "no secret"; a new vendor's token prefix belongs here.
    r"(?-i:hf_[A-Za-z0-9]{30,})",  # HuggingFace user access tokens
    r"(?-i:tfp_[A-Za-z0-9._-]{40,})",  # Typeform personal access tokens
    r"(?-i:napi_[a-z0-9]{20,})",  # Neon Postgres API keys
    r"(?-i:dckr_pat_[A-Za-z0-9_-]{20,})",  # Docker Hub personal access tokens
    r"(?-i:sbp_[a-f0-9]{40,})",  # Supabase service role tokens
    r"(?-i:shpat_[a-f0-9]{32})",  # Shopify admin API access tokens
    r"(?-i:lin_api_[A-Za-z0-9]{20,})",  # Linear API keys
    r"(?-i:wak_[A-Za-z0-9._-]{20,})",  # Vesta / Double Tick WhatsApp API keys, in ~/.whatsapp/state.json
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
    r"BEGIN [A-Z ]+ PRIVATE KEY",
    # A real separator (: = or a quote) is mandatory, so prose like "password reuse" never matches;
    # the \\? bits absorb the backslash JSON puts before an escaped quote in the raw `data` blob.
    # One factored keyword (the alternation is the expensive part, so it runs once per position)
    # with three value shapes: (1) a : or = carries the assignment by itself, so spaces and quotes
    # around it are free (password = "x", YAML password: x, JSON "password": "x"); (2) a bare quote
    # separates when the value starts right after it (--password "x"); (3) a space-padded value
    # inside quotes (password="  x") needs a separator before the quote AND a closing quote after
    # the value, because a quote plus a space also closes a quoted identifier in prose.
    (
        r"(?:password|secret|api[_-]?key)(?:"
        r"[ ]*\\?[\"']?[ ]*[:=]+[ ]*\\?[\"']?[^ \"'\\]{4,}"
        r"|[ ]*\\?[\"'][^ \"'\\]{4,}"
        r"|\\?[\"']?(?:[ ]*[:=]+[ ]*|[ ]+)\\?[\"'][ ]+[^ \"'\\]{4,}\\?[\"'])"
    ),
    # Any name ENDING in key/token/secret/password followed by : or =, so EXA_KEY=<tok>, an
    # X-Plex-Token: header, and a JSON "token" field all hit. The match anchors at the suffix word
    # itself: a quantified name-prefix here backtracks quadratically inside base64 runs and hangs
    # the scan on large events. Value guard: >=16 token chars with at least one digit keeps prose
    # ("the key = a good one") and identifier assignments (PRIMARY_KEY=account_number) out.
    r"(?:key|token|secret|password)\\?[\"']?[ ]*\\?[:=]+[ ]*\\?[\"']?(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{16,}",
    # `Authorization: Bearer <tok>`: the secret is named by the SCHEME, not by a key name.
    r"Bearer[ ]+(?=[A-Za-z0-9_\-.]*\d)[A-Za-z0-9_\-.]{16,}",
    r"(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis)://[^ \"']+",
    # Credentials embedded in URLs, where the secret is a query value or bare path segment with no
    # key-shaped name (a Hue bridge key travels as /api/<key>). Query params whose name ends in
    # key/token hit the named rule above; these are the names that don't. Both rules anchor at a
    # short literal ([?&] / the /api/ segment itself) rather than a quantified URL prefix, which
    # would rescan the rest of the text from every scheme occurrence and hang the scan on large
    # events. The digit lookahead keeps camelCase docs URLs (/api/RTCPeerConnectionIceEvent) out.
    r"[?&](?:auth|sig|signature)=[A-Za-z0-9_\-]{16,}",
    r"/api/(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{25,}",
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
# longer numeric id is never sliced into a fake PAN, and forbid a preceding DOT so the numeric tail
# of a dotted identifier is not read as one: namespaced catalogue ids (mdp.39015017012900) run 14
# digits from MII 3, clearing the IIN gate, and pass Luhn about one time in ten. A PAN follows a
# space, a colon or a quote, never a namespace, so the dot costs no real detection. The guard is
# deliberately dot-only: hyphen/underscore-namespaced ids stay flagged, erring toward redaction.
CARD_CANDIDATE = re.compile(r"(?<![\d.])\d(?:[ -]?\d){12,18}(?!\d)")
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
    Mastercard 2-series (2221 to 2720). Every major network issues inside those, so what this
    rejects (MII 0/1/7/8/9) is ids. The one card type left out is UATP airline travel (MII 1),
    deliberately: admitting MII 1 would re-flag more timestamp ids than it would catch cards."""
    if digits[0] in "3456":
        return True
    return digits[0] == "2" and 2221 <= int(digits[:4]) <= 2720


def _is_card(candidate: str) -> bool:
    """A candidate run is a real PAN only when its stripped digits count 13 to 19, pass Luhn, AND open
    with an assigned card issuer prefix. Luhn alone flags ~1 in 10 non-card digit runs (a 13-digit
    timestamp can pass by chance); the IIN gate removes that class without dropping a major-network card."""
    digits = candidate.replace(" ", "").replace("-", "")
    return 13 <= len(digits) <= 19 and _has_card_iin(digits) and luhn_valid(digits)


def redact_cards(text: str) -> str:
    """Replace every PAN with the placeholder, leaving other digit runs (order numbers, timestamps,
    tracking ids) untouched. The `_is_card` check cannot live inside the combined REGEX, so this is
    its own pass, run after REGEX everywhere REGEX runs. `[REDACTED]` holds no digit run, so a re-run
    never re-flags or mangles one, matching the regex path's idempotency."""
    return CARD_CANDIDATE.sub(lambda m: REDACTED if _is_card(m.group(0)) else m.group(0), text)


def _redact_text(text: str) -> str:
    """Both redaction passes over one string: pattern hits, then payment cards."""
    return redact_cards(REGEX.sub(mask, text))


type JsonValue = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None


def map_json_strings(value: JsonValue, transform: tp.Callable[[str], str]) -> JsonValue:
    """Apply one string transform to every string inside a parsed JSON value, dict keys included (a
    secret can sit as an object KEY, and a rewrite that only touches values leaves it). Rewriting
    the decoded structure (not the serialized blob) guarantees the re-serialized event is still
    valid JSON: a raw text substitution can splice `[REDACTED]` across a `\"`/escape boundary and
    corrupt the blob, which then breaks the json_extract in the FTS resync and rolls back the scrub."""
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, list):
        return [map_json_strings(v, transform) for v in value]
    if isinstance(value, dict):
        return {transform(k): map_json_strings(v, transform) for k, v in value.items()}
    return value


def _decoded(data: str) -> JsonValue | None:
    """The blob parsed as JSON, or None for a non-JSON payload, which every scrub path treats as raw
    text (nothing to keep valid)."""
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return None


def _mask_context(window: str) -> str:
    """Mask both pattern hits and payment cards in a scan snippet, so reviewing a candidate never
    re-leaks the value back into a new event (the old redaction loop's self-reseeding)."""
    return _redact_text(window).replace("\n", " ")


def _hit_spans(text: str) -> list[tuple[int, int]]:
    """Every real hit's span in one string: the combined REGEX (already-redacted spans and news-slug
    false positives filtered out) plus the payment-card pass."""
    spans = [m.span() for m in REGEX.finditer(text) if REDACTED not in m.group(0) and not _looks_like_word_slug(m.group(0))]
    spans += [m.span() for m in CARD_CANDIDATE.finditer(text) if _is_card(m.group(0))]
    return spans


def find_matches(text: str) -> list[str]:
    """Every secret in one string as a masked context snippet. Pure and DB-free, so the DB scan and
    the tests share exactly one detection path."""
    return [_mask_context(text[max(0, start - CONTEXT_CHARS) : end + CONTEXT_CHARS]) for start, end in _hit_spans(text)]


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


def _rows_by_id(conn: sqlite3.Connection, ids: list[int]) -> dict[int, str]:
    """Non-empty data blobs for the given event ids, in one query."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {row_id: data for row_id, data in conn.execute(f"SELECT id, data FROM events WHERE id IN ({marks})", ids) if data}


def stored_hits(conn: sqlite3.Connection, ids: list[int]) -> dict[int, list[str]]:
    """The exact matched substrings per event, captured before a scrub (held in memory only, never
    printed). Verification asks whether these literals survive in the committed rows, which is
    independent of the write path: a hit the detector saw but the rewrite failed to remove cannot
    hide behind being re-missed."""
    hits: dict[int, list[str]] = {}
    for row_id, data in _rows_by_id(conn, ids).items():
        if found := [data[start:end] for start, end in _hit_spans(data)]:
            hits[row_id] = found
    return hits


def still_matching(conn: sqlite3.Connection, hits: dict[int, list[str]]) -> list[int]:
    """Ids whose committed row still contains a pre-scrub matched literal: the rewrite could not
    reach that hit (a value outside a JSON string, a rolled-back commit). A scrub that changed
    something is not the same as an event that is clean, so the outcome is checked, not assumed."""
    rows = _rows_by_id(conn, list(hits))
    return sorted(row_id for row_id, row_hits in hits.items() if row_id in rows and any(hit in rows[row_id] for hit in row_hits))


def _contains_literal(value: JsonValue, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, list):
        return any(_contains_literal(v, secret) for v in value)
    if isinstance(value, dict):
        return any(secret in k or _contains_literal(v, secret) for k, v in value.items())
    return False


def count_literal(conn: sqlite3.Connection, secret: str) -> int:
    """Events still holding the literal, checked independently of the writer's own predicate, so the
    post-write count is a real verification of the committed rows. Both representations are checked:
    raw catches a copy outside any JSON string (a digits-only value stored as a bare JSON number,
    which the string rewrite never sees), decoded catches a copy whose special characters JSON
    escapes in the raw blob."""
    total = 0
    for (data,) in conn.execute("SELECT data FROM events"):
        if not data:
            continue
        if secret in data:
            total += 1
            continue
        obj = _decoded(data)
        if obj is not None and _contains_literal(obj, secret):
            total += 1
    return total


def _rewrite_rows(conn: sqlite3.Connection, rows: tp.Iterable[tuple[int, str]], transform: tp.Callable[[str], str]) -> int:
    """Rewrite every row's blob with one string transform, committing through write_scrubbed. A JSON
    blob is transformed per decoded string (map_json_strings) and re-serialized only when a real
    change happened, so events with no secret are never rewritten (a reformat-only diff would
    rewrite every event); json.dumps matches events.py's so a scrubbed blob keeps the fleet's byte
    representation. A non-JSON payload gets the transform as a raw text substitution."""
    changed: dict[int, str] = {}
    json_ids: list[int] = []
    for row_id, data in rows:
        if not data:
            continue
        obj = _decoded(data)
        if obj is None:
            new_data = transform(data)
            if new_data != data:
                changed[row_id] = new_data
            continue
        new_obj = map_json_strings(obj, transform)
        if new_obj != obj:
            changed[row_id] = json.dumps(new_obj)
            json_ids.append(row_id)
    return write_scrubbed(conn, changed, json_ids)


def scrub_literal(conn: sqlite3.Connection, secret: str) -> tuple[int, int]:
    """Redact every stored copy of one exact value, returning (events changed, events still holding
    it). Keyed by the literal rather than by pattern, because --scrub can only remove what the
    scanner DETECTS: a human-chosen password matches none of the shapes above, and this is the path
    for a value the operator knows exactly."""

    def replace(text: str) -> str:
        return text.replace(secret, REDACTED)

    count = _rewrite_rows(conn, conn.execute("SELECT id, data FROM events"), replace)
    return count, count_literal(conn, secret)


def scrub(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Redact every hit in the given events in place, keeping their context and events_fts. Driven by
    the same patterns and keyed by id, so the caller never has to pass (and thereby re-leak) the literal."""
    return _rewrite_rows(conn, _rows_by_id(conn, ids).items(), _redact_text)


def write_scrubbed(conn: sqlite3.Connection, changed: dict[int, str], json_ids: list[int]) -> int:
    """Commit rewritten event blobs, resyncing events_fts around the UPDATE; every scrub path goes
    through here. The resync spans only json_ids, the rows rewritten as decoded JSON: a non-JSON
    payload was never in the index, and json_extract over a malformed blob aborts the whole
    statement."""
    if not changed:
        return 0
    id_marks = ",".join("?" * len(json_ids))
    fts_where = f"id IN ({id_marks}) AND {FTS_INDEXED}"
    if json_ids:
        conn.execute(
            f"INSERT INTO events_fts(events_fts, rowid, text_content) SELECT 'delete', id, {FTS_TEXT} FROM events WHERE {fts_where}",
            json_ids,
        )
    conn.executemany("UPDATE events SET data = ? WHERE id = ?", [(new_data, row_id) for row_id, new_data in changed.items()])
    if json_ids:
        conn.execute(
            f"INSERT INTO events_fts(rowid, text_content) SELECT id, {FTS_TEXT} FROM events WHERE {fts_where}",
            json_ids,
        )
    conn.commit()
    return len(changed)


def _run_scrub(conn: sqlite3.Connection, ids: list[int]) -> int:
    hits = stored_hits(conn, ids)
    scrubbed = scrub(conn, ids)
    print(f"Scrubbed secrets in {scrubbed} event(s) in place.")
    if scrubbed == 0:
        print(
            "0 events changed, which does NOT mean they were clean: --scrub can only remove a\n"
            "value the scanner detects. For a value it does not recognise (a human-chosen\n"
            "password matches no API-key shape), redact it by value instead:\n"
            "redact_secrets.sh --scrub-literal '<value>'"
        )
    if remaining := still_matching(conn, hits):
        print(
            f"WARNING: {len(remaining)} event(s) still hold a matched secret after scrubbing: "
            f"{', '.join(str(i) for i in remaining)}. The rewrite could not reach every hit "
            "(a value outside a JSON string, a rolled-back commit). Redact by value with "
            "--scrub-literal, or fix by hand and resync events_fts."
        )
        return 2
    return 0


def _run_scrub_literal(conn: sqlite3.Connection, rest: list[str]) -> int:
    if len(rest) != 1 or not rest[0]:
        print("usage: redact_secrets.sh --scrub-literal '<exact value>'")
        return 1
    secret = rest[0]
    if len(secret) < MIN_LITERAL_LEN:
        print(
            f"Refusing to scrub a literal shorter than {MIN_LITERAL_LEN} chars: the rewrite is "
            "DB-wide, and a short value would splice the placeholder through unrelated text."
        )
        return 1
    scrubbed, remaining = scrub_literal(conn, secret)
    # Report the shape, never the value: this process's own output is itself recorded.
    print(f"Scrubbed {scrubbed} event(s); {remaining} remain. (length {len(secret)}, value not echoed)")
    if remaining:
        print(
            "The remaining event(s) hold the value where a JSON rewrite cannot reach it "
            "(e.g. a bare JSON number): fix those events by hand and resync events_fts."
        )
        return 2
    print("Re-run this command once more later: the event recording this run may also hold the value.")
    return 0


def _run_show(conn: sqlite3.Connection, rest: list[str]) -> int:
    """Print one event's full `data` with every scanner-detected secret masked, for judging a hit
    whose scan snippet is too short. Runs through the same redaction pass as the scrub, so no value
    the scanner detects reaches the output."""
    if len(rest) != 1 or not rest[0].isdigit():
        print("usage: redact_secrets.sh --show <event-id>", file=sys.stderr)
        return 1
    row = conn.execute("SELECT data FROM events WHERE id = ?", (int(rest[0]),)).fetchone()
    if row is None or not row[0]:
        print(f"no event with id {rest[0]}", file=sys.stderr)
        return 1
    print(_redact_text(row[0]))
    return 0


def main() -> int:
    if not DB.is_file():
        print(f"No database at {DB}", file=sys.stderr)
        return 1

    args = sys.argv[1:]
    conn = sqlite3.connect(DB)
    try:
        if args[:1] == ["--show"]:
            return _run_show(conn, args[1:])

        if args[:1] == ["--scrub"]:
            return _run_scrub(conn, [int(arg) for arg in args[1:]])

        if args[:1] == ["--scrub-literal"]:
            return _run_scrub_literal(conn, args[1:])

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
