#!/usr/bin/env python3
"""Scan the events DB and every channel store on the box for secrets, then scrub the real leaks in place.
A hit reference is a bare event id for the events store, or store:table:rowid for a channel store,
exactly as the scan prints it.
Usage: redact_secrets.py            # scan every store present, printing each hit with the value masked
       redact_secrets.py --show REF # print one row's full text with every detected secret masked
       redact_secrets.py --scrub REF [REF ...]   # redact every secret in those rows
       redact_secrets.py --scrub-literal 'VALUE'   # redact one known value the scanner can't detect
"""

import dataclasses
import json
import re
import sqlite3
import sys
import time
import typing as tp
from pathlib import Path

DB = Path("~/agent/data/events.db").expanduser()
# Channel stores can be large (a year of chat history), so each store's scan gets a hard time
# budget; a store that exceeds it is reported TRUNCATED, never silently half-scanned as clean.
STORE_SCAN_BUDGET_SECS = 120
SCAN_BATCH_ROWS = 256
CONN_TIMEOUT_SECS = 30
# The tables FTS5 creates behind a virtual table: binary index shards, never scanned directly.
_FTS_SHADOW_SUFFIXES = ("_data", "_idx", "_content", "_docsize", "_config")
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


@dataclasses.dataclass(frozen=True)
class Store:
    """One scannable database: a short name (the ref prefix in scan output) and its path."""

    name: str
    path: Path


@dataclasses.dataclass(frozen=True)
class EventsFts:
    """The resync predicate for an events-shaped store's external-content FTS index: which rows the
    store's own triggers index, and the expression they index. Must mirror those triggers exactly,
    or the manual delete during a scrub misses the index row and corrupts the index."""

    indexed: str
    text: str


CORE_FTS = EventsFts(indexed=FTS_INDEXED, text=FTS_TEXT)
# The app-chat store (skills/app-chat/cli/src/app_chat_cli/store.py): same events(id, ts, data)
# shape, but its triggers index only user/chat rows by $.text.
APP_CHAT_FTS = EventsFts(indexed="(json_extract(data, '$.type') IN ('user', 'chat'))", text="json_extract(data, '$.text')")
# The stores holding JSON event blobs behind an external-content FTS index with insert/delete
# triggers only: a scrub must rewrite the decoded JSON and resync the index itself. Every other
# store goes through the generic per-cell path.
JSON_EVENT_FTS = {"events": CORE_FTS, "app-chat": APP_CHAT_FTS}


def channel_stores() -> list[Store]:
    """Every known channel store location, resolved from $HOME at call time. What the user actually
    typed lives in these, not in events.db, so a scan of events.db alone reports clean while a
    pasted credential sits in a messaging store. whatsapp and telegram keep one store per instance
    (the bare directory for the default one, a named subdirectory otherwise). The whatsmeow session
    store (~/.whatsapp/whatsapp.db) is deliberately not listed: it holds the channel's own
    crypto/session key material by design, and a scrub there breaks the device pairing."""
    home = Path.home()
    stores = [
        Store("app-chat", home / ".app-chat" / "app-chat.db"),
        Store("tasks", home / ".tasks" / "tasks.db"),
        Store("email-client", home / ".email-client" / "pending-sends.db"),
        Store("microsoft", home / ".microsoft" / "pending-sends.db"),
        Store("google", home / ".google" / "pending-sends.db"),
    ]
    for channel in ("whatsapp", "telegram"):
        base = home / f".{channel}"
        stores.append(Store(channel, base / "messages.db"))
        if base.is_dir():
            stores.extend(
                Store(f"{channel}/{instance.name}", instance / "messages.db")
                for instance in sorted(base.iterdir())
                if instance.is_dir() and (instance / "messages.db").is_file()
            )
    return stores


def _all_stores() -> dict[str, Store]:
    return {"events": Store("events", DB)} | {store.name: store for store in channel_stores()}


def _connect(path: Path) -> sqlite3.Connection:
    """Open a store and fold its WAL into the main file (TRUNCATE), so the scan's SQL view and the
    file's bytes agree: a clean report then means the db file itself holds no secret, not just the
    checkpointed part of it. Best effort: a busy store reports busy instead of raising, and the SQL
    view reads through the WAL either way."""
    conn = sqlite3.connect(path, timeout=CONN_TIMEOUT_SECS)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return conn


PATTERNS = [
    r"sk-[a-zA-Z0-9_-]{20,}",
    # Stripe secret + restricted keys use an UNDERSCORE (sk_live_ / sk_test_ / rk_live_ / rk_test_),
    # so the sk- (hyphen) pattern above never matched them. Publishable pk_ keys are not secret and
    # are deliberately excluded.
    r"[sr]k_(?:live|test)_[0-9a-zA-Z]{20,}",
    r"xox[bp]-[0-9A-Za-z-]+",
    # GitHub App installation tokens are ghs_<installation-id>_<jwt> (the format `upstream token`
    # hands out), so the class allows underscores and dots: without them the match dies at the
    # first underscore and a truncated copy escapes entirely. The prefix class carries
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
    # Apple app-specific password pasted BARE. Every rule above needs a label, prefix or URL around
    # the value, so none fire on a credential typed straight into chat, which is how users send one.
    # Format is fixed: four groups of four lowercase letters, matched case-sensitively (as AKIA is)
    # so mixed-case kebab identifiers cannot collide.
    # Four consecutive four-letter lowercase words match too. Deliberate: scanning only LISTS
    # candidates and --scrub is a separate explicit step, so a false positive costs a review line.
    r"(?-i:\b[a-z]{4}-[a-z]{4}-[a-z]{4}-[a-z]{4}\b)",
    r"(?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|redis)://[^ \"']+",
    # Credentials embedded in URLs, where the secret is a query value or bare path segment with no
    # key-shaped name (a Hue bridge key travels as /api/<key>). Query params whose name ends in
    # key/token hit the named rule above; these are the names that don't. Both rules anchor at a
    # short literal ([?&] / the /api/ segment itself) rather than a quantified URL prefix, which
    # would rescan the rest of the text from every scheme occurrence and hang the scan on large
    # events. The digit lookahead keeps camelCase docs URLs (/api/RTCPeerConnectionIceEvent) out.
    r"[?&](?:auth|sig|signature)=[A-Za-z0-9_\-]{16,}",
    r"/api/(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{25,}",
    # ENV-VAR ASSIGNMENT, added 21 Aug 2026, and the first STRUCTURAL rule here rather than another
    # vendor prefix. Every rule above needs a known prefix, and the header says so honestly: a clean
    # scan means "no known-shape secret", never "no secret". A key with no vendor prefix is simply
    # invisible.
    #
    # FOUND by breaking my own rule. Checking whether a Webshare subscription was mine, I ran a
    # plain `grep -n webshare ~/.bashrc` and printed a live 40-character API key into my own output,
    # which put it in the event store. I then claimed the nightly scrub would catch it by pattern.
    # It would not have: the scanner reported 7,147 hits and ZERO of them were this key. Eight
    # events had to be scrubbed by hand.
    #
    # A variable whose NAME ends in key/token/secret/password is the credential-holder's own label,
    # so it needs no entropy guessing and no vendor list. This is the rule that would have caught it.
    # Case-anchored for the reason AKIA is: under the outer IGNORECASE, [A-Z] matches lowercase, so
    # `my_api_key = get_it()` in ordinary code read as a credential. Real env vars are uppercase.
    r"(?-i:\b[A-Z][A-Z0-9_]*_(?:API_)?(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD))\s*=\s*[\"']?[A-Za-z0-9_\-\.]{16,}",
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
_DIGIT_RUN = r"(?<![\d.])\d(?:[ -]?\d){12,18}(?!\d)"
# A messaging id is a digit run wearing a suffix. A WhatsApp LID collides with the Mastercard
# 2-series head-on: 251638040256599 opens 2516 (inside 2221-2720), clears the IIN gate and passes
# Luhn by chance, so it is indistinguishable from a PAN by digits alone. The suffix is the only
# discriminator there is, and the hit count scales with how much chat traffic a box carries.
_MESSAGING_ID_SUFFIX = r"(?!@(?:lid|s\.whatsapp\.net|c\.us|g\.us)\b)"
CARD_CANDIDATE = re.compile(_DIGIT_RUN + _MESSAGING_ID_SUFFIX)
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
    timestamp can pass by chance); the IIN gate removes that class without dropping a major-network card.
    The 13 floor deliberately excludes legacy 12-digit Maestro: a 12-digit run is usually a phone
    number, and country codes 30-69 clear the IIN gate, so admitting 12 would flag chats wholesale."""
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


def _rewrite_rows(
    conn: sqlite3.Connection, rows: tp.Iterable[tuple[int, str]], transform: tp.Callable[[str], str], fts: EventsFts = CORE_FTS
) -> int:
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
    return write_scrubbed(conn, changed, json_ids, fts)


def scrub_literal(conn: sqlite3.Connection, secret: str, fts: EventsFts = CORE_FTS) -> tuple[int, int]:
    """Redact every stored copy of one exact value, returning (events changed, events still holding
    it). Keyed by the literal rather than by pattern, because --scrub can only remove what the
    scanner DETECTS: a human-chosen password matches none of the shapes above, and this is the path
    for a value the operator knows exactly."""

    def replace(text: str) -> str:
        return text.replace(secret, REDACTED)

    count = _rewrite_rows(conn, conn.execute("SELECT id, data FROM events"), replace, fts)
    return count, count_literal(conn, secret)


def scrub(conn: sqlite3.Connection, ids: list[int], fts: EventsFts = CORE_FTS) -> int:
    """Redact every hit in the given events in place, keeping their context and events_fts. Driven by
    the same patterns and keyed by id, so the caller never has to pass (and thereby re-leak) the literal."""
    return _rewrite_rows(conn, _rows_by_id(conn, ids).items(), _redact_text, fts)


def write_scrubbed(conn: sqlite3.Connection, changed: dict[int, str], json_ids: list[int], fts: EventsFts = CORE_FTS) -> int:
    """Commit rewritten event blobs, resyncing events_fts around the UPDATE; every scrub path goes
    through here. The resync spans only json_ids, the rows rewritten as decoded JSON: a non-JSON
    payload was never in the index, and json_extract over a malformed blob aborts the whole
    statement."""
    if not changed:
        return 0
    id_marks = ",".join("?" * len(json_ids))
    fts_where = f"id IN ({id_marks}) AND {fts.indexed}"
    if json_ids:
        conn.execute(
            f"INSERT INTO events_fts(events_fts, rowid, text_content) SELECT 'delete', id, {fts.text} FROM events WHERE {fts_where}",
            json_ids,
        )
    conn.executemany("UPDATE events SET data = ? WHERE id = ?", [(new_data, row_id) for row_id, new_data in changed.items()])
    if json_ids:
        conn.execute(
            f"INSERT INTO events_fts(rowid, text_content) SELECT id, {fts.text} FROM events WHERE {fts_where}",
            json_ids,
        )
    conn.commit()
    return len(changed)


def _store_tables(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    """(tables to scan, external-content FTS tables). A contentful FTS5 virtual table is scanned and
    scrubbed like any table (an UPDATE on it maintains its own index); an external-content one
    mirrors a base table that is already scanned, rejects UPDATEs, and needs its own resync after a
    scrub of its base. FTS shadow tables are binary index shards, never scanned."""
    rows = [(name, " ".join(table_sql.lower().split())) for name, table_sql in _table_ddl(conn)]
    fts = {name for name, table_sql in rows if "using fts5" in table_sql}
    external = {name for name, table_sql in rows if name in fts and "content=" in table_sql.replace(" ", "")}
    shadows = {f"{name}{suffix}" for name in fts for suffix in _FTS_SHADOW_SUFFIXES}
    scannable = [name for name, _ in rows if name not in shadows and name not in external and not name.startswith("sqlite_")]
    return scannable, sorted(external)


def _table_ddl(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL").fetchall()


type CellValue = str | bytes | int | float | None


def _cell_text(value: CellValue) -> str | None:
    """The scannable text of a cell: a str as-is, a BLOB decoded latin-1, else None. latin-1 is a
    lossless 1:1 byte<->codepoint map, so re-encoding a scrubbed BLOB restores every unmatched byte.
    An outbound email is queued as a payload BLOB, so a scan that reads only str cells certifies the
    send queue clean while a pasted credential rides in it."""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("latin-1")
    return None


def _scannable_cells(conn: sqlite3.Connection, table: str, rowid: int) -> dict[str, str | bytes]:
    """One row's str and BLOB cells by column name, keeping each cell's storage type so a scrub
    writes a BLOB back as a BLOB; a missing row is an empty dict."""
    cursor = conn.execute(f'SELECT * FROM "{table}" WHERE rowid = ?', (rowid,))
    row = cursor.fetchone()
    if row is None:
        return {}
    names = [description[0] for description in cursor.description]
    return {name: value for name, value in zip(names, row, strict=True) if isinstance(value, str | bytes)}


def _channel_row(conn: sqlite3.Connection, table: str, rowid: int) -> dict[str, str]:
    """One row's scannable cells as text by column name (a BLOB decoded latin-1); a missing row is
    an empty dict. The scrub reads types through `_scannable_cells` so it can write a BLOB back."""
    return {name: text for name, value in _scannable_cells(conn, table, rowid).items() if (text := _cell_text(value)) is not None}


def channel_stored_hits(conn: sqlite3.Connection, refs: list[tuple[str, int]]) -> dict[tuple[str, int], list[str]]:
    """The exact matched substrings per (table, rowid), captured before a scrub: the channel-store
    counterpart of stored_hits, feeding the same verify-the-committed-rows check."""
    hits: dict[tuple[str, int], list[str]] = {}
    for table, rowid in refs:
        found = [text[start:end] for text in _channel_row(conn, table, rowid).values() for start, end in _hit_spans(text)]
        if found:
            hits[(table, rowid)] = found
    return hits


def channel_still_matching(conn: sqlite3.Connection, hits: dict[tuple[str, int], list[str]]) -> list[tuple[str, int]]:
    return sorted(
        (table, rowid)
        for (table, rowid), row_hits in hits.items()
        if any(hit in text for text in _channel_row(conn, table, rowid).values() for hit in row_hits)
    )


def _transform_cell(text: str, transform: tp.Callable[[str], str]) -> str:
    """One text cell through a transform: a JSON object or array is rewritten through its decoded
    structure so the stored blob stays valid JSON (app-chat cells are JSON event blobs; splicing the
    placeholder across an escape boundary would corrupt them), anything else as raw text."""
    obj = _decoded(text)
    if isinstance(obj, dict | list):
        new_obj = map_json_strings(obj, transform)
        return json.dumps(new_obj) if new_obj != obj else text
    return transform(text)


def _cell_updates(cells: tp.Iterable[tuple[str, CellValue]], transform: tp.Callable[[str], str]) -> dict[str, str | bytes]:
    """Each cell rewritten through the transform, kept only where the text actually changed and
    keyed by column; a BLOB is re-encoded latin-1 so it is written back as a BLOB, not retyped."""
    updates: dict[str, str | bytes] = {}
    for column, value in cells:
        text = _cell_text(value)
        if text is not None and (new_text := _transform_cell(text, transform)) != text:
            updates[column] = new_text.encode("latin-1") if isinstance(value, bytes) else new_text
    return updates


def _apply_cell_updates(conn: sqlite3.Connection, table: str, rowid: int, updates: dict[str, str | bytes]) -> None:
    assignments = ", ".join(f'"{column}" = ?' for column in updates)
    conn.execute(f'UPDATE "{table}" SET {assignments} WHERE rowid = ?', [*updates.values(), rowid])


def scrub_channel_rows(conn: sqlite3.Connection, refs: list[tuple[str, int]]) -> int:
    """Redact every hit in the given channel-store rows in place, text cell by text cell. A
    contentful FTS mirror is reached either by the store's own AFTER UPDATE trigger or by the
    mirror row's own reference; both are idempotent, so hitting a row twice never mangles it."""
    changed = 0
    for table, rowid in refs:
        if updates := _cell_updates(_scannable_cells(conn, table, rowid).items(), _redact_text):
            _apply_cell_updates(conn, table, rowid, updates)
            changed += 1
    conn.commit()
    return changed


def _cell_holds(text: str, secret: str) -> bool:
    if secret in text:
        return True
    obj = _decoded(text)
    return obj is not None and _contains_literal(obj, secret)


def channel_rows_holding(conn: sqlite3.Connection, secret: str) -> int:
    """Rows anywhere in the store still holding the literal, checked raw and decoded exactly as
    count_literal checks events, so the post-scrub count is a real verification."""
    total = 0
    for table in _store_tables(conn)[0]:
        cursor = conn.execute(f'SELECT rowid, * FROM "{table}"')
        while rows := cursor.fetchmany(SCAN_BATCH_ROWS):
            total += sum(1 for row in rows if any((text := _cell_text(value)) is not None and _cell_holds(text, secret) for value in row[1:]))
    return total


def scrub_literal_channel(conn: sqlite3.Connection, secret: str) -> tuple[int, int]:
    """Redact every stored copy of one exact value across a channel store, returning (rows changed,
    rows still holding it)."""

    def replace(text: str) -> str:
        return text.replace(secret, REDACTED)

    changed = sum(_replace_in_table(conn, table, replace) for table in _store_tables(conn)[0])
    conn.commit()
    return changed, channel_rows_holding(conn, secret)


def _replace_in_table(conn: sqlite3.Connection, table: str, transform: tp.Callable[[str], str]) -> int:
    cursor = conn.execute(f'SELECT rowid, * FROM "{table}"')
    names = [description[0] for description in cursor.description]
    pending: list[tuple[int, dict[str, str | bytes]]] = []
    while rows := cursor.fetchmany(SCAN_BATCH_ROWS):
        pending.extend((row[0], updates) for row in rows if (updates := _cell_updates(zip(names[1:], row[1:], strict=True), transform)))
    for rowid, updates in pending:
        _apply_cell_updates(conn, table, rowid, updates)
    return len(pending)


def flush_wal_and_free_pages(conn: sqlite3.Connection) -> str | None:
    """Fold the WAL into the main file, truncate it, and rewrite the file so no freed page keeps the
    pre-scrub bytes: without this, a scrub whose SQL view reads clean leaves the secret's bytes in
    the -wal sidecar until some later checkpoint, and in free pages of the main file indefinitely.
    Returns a warning when the store was too busy to finish; the byte-level verification then
    decides whether that mattered."""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    except sqlite3.OperationalError as exc:
        return f"could not checkpoint and vacuum ({exc}): scrubbed bytes may linger on disk"
    return None


def bytes_on_disk(path: Path, literals: list[str]) -> list[str]:
    """The literals present at byte level in the db file or its -wal/-shm sidecars: the check that
    catches what the SQL view cannot show, a pre-scrub page image surviving in the WAL or a freed
    page. Chunks overlap by the longest literal so a value straddling a chunk boundary still hits."""
    needles = {literal.encode() for literal in literals}
    if not needles:
        return []
    overlap = max(len(needle) for needle in needles)
    found: set[bytes] = set()
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if not candidate.is_file():
            continue
        tail = b""
        with candidate.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                window = tail + chunk
                found.update(needle for needle in needles if needle in window)
                tail = window[-overlap:]
    return sorted(needle.decode() for needle in found)


def _parse_ref(token: str) -> tuple[str, str, int]:
    """A hit reference as (store, table, rowid): a bare integer addresses the events store, and
    store:table:rowid addresses a channel-store row, exactly as the scan printed it."""
    if token.isdigit():
        return ("events", "events", int(token))
    store_name, _, tail = token.rpartition(":")
    store_name, _, table = store_name.rpartition(":")
    if not store_name or not table or not tail.isdigit():
        raise ValueError(token)
    return (store_name, table, int(tail))


def _scrub_store(conn: sqlite3.Connection, store: Store, refs: list[tuple[str, int]]) -> tuple[int, int]:
    """Scrub the given rows of one store and verify the outcome, returning (rows changed, exit
    code). JSON-event stores go through the id-keyed JSON path with their FTS resync; everything
    else through the generic per-cell path."""
    if store.name in JSON_EVENT_FTS:
        ids = [rowid for _, rowid in refs]
        event_hits = stored_hits(conn, ids)
        changed = scrub(conn, ids, fts=JSON_EVENT_FTS[store.name])
        survivors = [("events", rowid) for rowid in still_matching(conn, event_hits)]
        hits = {("events", rowid): row_hits for rowid, row_hits in event_hits.items()}
        counter: tp.Callable[[sqlite3.Connection, str], int] = count_literal
    else:
        tables = _store_tables(conn)[0]
        if unknown := sorted({table for table, _ in refs if table not in tables}):
            print(f"{store.name}: no such table(s): {', '.join(unknown)}", file=sys.stderr)
            return 0, 1
        hits = channel_stored_hits(conn, refs)
        changed = scrub_channel_rows(conn, refs)
        survivors = channel_still_matching(conn, hits)
        counter = channel_rows_holding
    print(f"{store.name}: scrubbed secrets in {changed} row(s) in place.")
    if warning := flush_wal_and_free_pages(conn):
        print(f"WARNING: {store.name}: {warning}")
    code = 0
    if survivors:
        labels = ", ".join(str(rowid) if store.name == "events" else f"{store.name}:{table}:{rowid}" for table, rowid in survivors)
        print(
            f"WARNING: {len(survivors)} row(s) still hold a matched secret after scrubbing: "
            f"{labels}. The rewrite could not reach every hit "
            "(a value outside a JSON string, a rolled-back commit). Redact by value with "
            "--scrub-literal, or fix by hand."
        )
        code = 2
    literals = sorted({literal for row_hits in hits.values() for literal in row_hits})
    if lingering := bytes_on_disk(store.path, [literal for literal in literals if counter(conn, literal) == 0]):
        print(
            f"WARNING: {store.name}: {len(lingering)} scrubbed value(s) still present at byte level in the db file or its "
            "-wal/-shm sidecars. Re-run --scrub for this store once its daemon is idle, so the checkpoint and vacuum can finish."
        )
        code = 2
    return changed, code


def _run_scrub(tokens: list[str]) -> int:
    try:
        refs = [_parse_ref(token) for token in tokens]
    except ValueError as exc:
        print(f"bad reference {exc}: use a numeric event id or store:table:rowid from the scan output", file=sys.stderr)
        return 1
    if not refs:
        print("usage: redact_secrets.sh --scrub <ref> <ref> ...", file=sys.stderr)
        return 1
    stores = _all_stores()
    code = 0
    total = 0
    for name in sorted({store_name for store_name, _, _ in refs}):
        if name not in stores or not stores[name].path.is_file():
            print(f"no store '{name}' on this box", file=sys.stderr)
            return 1
        store_refs = [(table, rowid) for store_name, table, rowid in refs if store_name == name]
        conn = _connect(stores[name].path)
        try:
            changed, store_code = _scrub_store(conn, stores[name], store_refs)
        finally:
            conn.close()
        total += changed
        code = max(code, store_code)
    if total == 0:
        print(
            "0 rows changed, which does NOT mean they were clean: --scrub can only remove a\n"
            "value the scanner detects. For a value it does not recognise (a human-chosen\n"
            "password matches no API-key shape), redact it by value instead:\n"
            "redact_secrets.sh --scrub-literal '<value>'"
        )
    return code


def _scrub_literal_store(conn: sqlite3.Connection, store: Store, secret: str) -> tuple[int, int, int]:
    """One store's literal sweep: (rows scrubbed, rows still holding the value, exit code)."""
    if store.name in JSON_EVENT_FTS:
        scrubbed, remaining = scrub_literal(conn, secret, fts=JSON_EVENT_FTS[store.name])
    else:
        scrubbed, remaining = scrub_literal_channel(conn, secret)
    if warning := flush_wal_and_free_pages(conn):
        print(f"WARNING: {store.name}: {warning}")
    code = 0
    if remaining == 0 and bytes_on_disk(store.path, [secret]):
        print(
            f"WARNING: {store.name}: the value still sits at byte level in the db file or its -wal/-shm sidecars. "
            "Re-run this command once the store's daemon is idle, so the checkpoint and vacuum can finish."
        )
        code = 2
    return scrubbed, remaining, code


def _run_scrub_literal(rest: list[str]) -> int:
    if len(rest) != 1 or not rest[0]:
        print("usage: redact_secrets.sh --scrub-literal '<exact value>'", file=sys.stderr)
        return 1
    secret = rest[0]
    if len(secret) < MIN_LITERAL_LEN:
        print(
            f"Refusing to scrub a literal shorter than {MIN_LITERAL_LEN} chars: the rewrite is "
            "DB-wide, and a short value would splice the placeholder through unrelated text.",
            file=sys.stderr,
        )
        return 1
    stores = [store for store in _all_stores().values() if store.path.is_file()]
    if not stores:
        print(f"No database at {DB}", file=sys.stderr)
        return 1
    total_remaining = 0
    code = 0
    for store in stores:
        conn = _connect(store.path)
        try:
            scrubbed, remaining, store_code = _scrub_literal_store(conn, store, secret)
        finally:
            conn.close()
        total_remaining += remaining
        code = max(code, store_code)
        # Report the shape, never the value: this process's own output is itself recorded.
        print(f"{store.name}: scrubbed {scrubbed} row(s); {remaining} remain.")
    print(f"(length {len(secret)}, value not echoed)")
    if total_remaining:
        print("The remaining row(s) hold the value where a JSON rewrite cannot reach it (e.g. a bare JSON number): fix those rows by hand.")
        return 2
    if code == 0:
        print("Re-run this command once more later: the event recording this run may also hold the value.")
    return code


def _run_show(rest: list[str]) -> int:
    """Print one row's full text with every scanner-detected secret masked, for judging a hit whose
    scan snippet is too short. Runs through the same redaction pass as the scrub, so no value the
    scanner detects reaches the output."""
    try:
        (ref,) = rest
        store_name, table, rowid = _parse_ref(ref)
    except ValueError:
        print("usage: redact_secrets.sh --show <ref>   (a numeric event id, or store:table:rowid)", file=sys.stderr)
        return 1
    stores = _all_stores()
    if store_name not in stores or not stores[store_name].path.is_file():
        print(f"no store '{store_name}' on this box", file=sys.stderr)
        return 1
    conn = _connect(stores[store_name].path)
    try:
        if store_name in JSON_EVENT_FTS:
            row = conn.execute("SELECT data FROM events WHERE id = ?", (rowid,)).fetchone()
            if row is None or not row[0]:
                print(f"no event with id {rowid}", file=sys.stderr)
                return 1
            print(_redact_text(row[0]))
            return 0
        cells = _channel_row(conn, table, rowid)
        if not cells:
            print(f"no row {ref}", file=sys.stderr)
            return 1
        for column, value in cells.items():
            print(f"{column}: {_redact_text(value)}")
        return 0
    finally:
        conn.close()


@dataclasses.dataclass(frozen=True)
class StoreReport:
    """One store's scan outcome: a status line for the coverage block, and its hits as
    (ref token, masked snippet)."""

    store: Store
    status: str
    hits: list[tuple[str, str]]


def scan_channel_store(conn: sqlite3.Connection, store: Store) -> StoreReport:
    """Sweep every text cell of every scannable table, under the store's time budget. A store that
    outruns the budget is reported TRUNCATED, loudly: a half-scanned store reported clean is the
    exact false negative this scanner exists to prevent."""
    deadline = time.monotonic() + STORE_SCAN_BUDGET_SECS
    tables = _store_tables(conn)[0]
    hits: list[tuple[str, str]] = []
    for table in tables:
        if not _scan_table(conn, store, table, deadline, hits):
            return StoreReport(store, f"TRUNCATED after {STORE_SCAN_BUDGET_SECS}s in table {table}: NOT fully scanned", hits)
    return StoreReport(store, f"scanned {len(tables)} table(s)", hits)


def _scan_table(conn: sqlite3.Connection, store: Store, table: str, deadline: float, hits: list[tuple[str, str]]) -> bool:
    cursor = conn.execute(f'SELECT rowid, * FROM "{table}"')
    while rows := cursor.fetchmany(SCAN_BATCH_ROWS):
        if time.monotonic() > deadline:
            return False
        for row in rows:
            for value in row[1:]:
                text = _cell_text(value)
                if text is not None:
                    hits.extend((f"{store.name}:{table}:{row[0]}", snippet) for snippet in find_matches(text))
    return True


def _scan_events_store() -> StoreReport:
    store = Store("events", DB)
    if not DB.is_file():
        return StoreReport(store, "absent", [])
    conn = _connect(DB)
    try:
        return StoreReport(store, "scanned 1 table(s)", [(str(row_id), snippet) for row_id, snippet in scan(conn)])
    finally:
        conn.close()


def _scan_one_channel(store: Store) -> StoreReport:
    if not store.path.is_file():
        return StoreReport(store, "absent", [])
    try:
        conn = _connect(store.path)
        try:
            return scan_channel_store(conn, store)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return StoreReport(store, f"FAILED ({exc}): NOT scanned", [])


def _run_scan() -> int:
    reports = [_scan_events_store(), *(_scan_one_channel(store) for store in channel_stores())]
    if all(report.status == "absent" for report in reports):
        print(f"No database at {DB}", file=sys.stderr)
        return 1
    print("Store coverage (a store not marked scanned was NOT checked):")
    for report in reports:
        line = f"  {report.store.name} ({report.store.path}): {report.status}"
        if report.status != "absent":
            line += f", {len(report.hits)} hit(s)"
        print(line)
    partial = [report for report in reports if not report.status.startswith(("scanned", "absent"))]
    hits = [hit for report in reports for hit in report.hits]
    if not hits:
        print("No secrets found." if not partial else "No secrets found in what was scanned; the coverage above shows what was not.")
        return 0
    refs = {token for token, _ in hits}
    print(f"Found {len(refs)} record(s) with potential secrets (value masked below).")
    print("Review the context, then redact the real leaks: redact_secrets.sh --scrub <ref> <ref> ...")
    # Never cap this list: matches arrive in row order, so any cap hides the newest rows' leaks.
    for token, snippet in hits:
        print(f"{token}|{snippet}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--show"]:
        return _run_show(args[1:])
    if args[:1] == ["--scrub"]:
        return _run_scrub(args[1:])
    if args[:1] == ["--scrub-literal"]:
        return _run_scrub_literal(args[1:])
    return _run_scan()


if __name__ == "__main__":
    sys.exit(main())
