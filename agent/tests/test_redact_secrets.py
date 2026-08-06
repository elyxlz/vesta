"""Tests for the dream skill's redact_secrets script: masked pattern scan + in-place scrub by id."""

import importlib.util
import json
import os
import pathlib as pl
import sqlite3
import subprocess
import typing as tp

import pytest

from core.events import AssistantEvent, NotificationEvent

SCRIPT = pl.Path(__file__).resolve().parents[1] / "skills" / "dream" / "scripts" / "redact_secrets.py"

spec = importlib.util.spec_from_file_location("redact_secrets", SCRIPT)
assert spec is not None and spec.loader is not None
redact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redact)

SECRET = "AKIAABCDEFGHIJKLMNOP"


@pytest.fixture
def db_conn(tmp_path, event_bus):
    conn = sqlite3.connect(str(tmp_path / "events.db"))
    yield conn
    conn.close()


def test_scan_masks_the_secret_but_keeps_context(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text=f"the aws key is {SECRET} for backups"))

    matches = redact.scan(db_conn)

    assert len(matches) == 1
    _, snippet = matches[0]
    assert SECRET not in snippet
    assert "[REDACTED]" in snippet
    assert "the aws key is" in snippet and "for backups" in snippet


def test_scan_reports_every_match_in_an_event(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text="first AKIAABCDEFGHIJKLMNOP then xoxb-1234-abcdef in one message"))

    matches = redact.scan(db_conn)

    assert len(matches) == 2
    assert all("AKIA" not in snippet and "xoxb-1234" not in snippet for _, snippet in matches)


def test_scrub_redacts_the_secret_in_place_and_keeps_context(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text=f"leaked {SECRET} during backup"))
    ids = sorted({row_id for row_id, _ in redact.scan(db_conn)})

    assert redact.scrub(db_conn, ids) == 1

    data = db_conn.execute("SELECT data FROM events").fetchone()[0]
    assert SECRET not in data
    assert "leaked [REDACTED] during backup" in data


def test_scrub_keeps_fts_in_sync(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text=f"leaked {SECRET} during backup"))

    redact.scrub(db_conn, [row_id for row_id, _ in redact.scan(db_conn)])

    assert event_bus.search(SECRET) == []
    hits = event_bus.search("backup")
    assert len(hits) == 1
    assert "[REDACTED]" in hits[0]["text"]

    db_conn.execute("DELETE FROM events")
    db_conn.commit()
    assert event_bus.search("backup") == []


def test_scrub_keeps_fts_in_sync_for_an_inbound_message(event_bus, db_conn):
    """An inbound message is indexed by its `summary`, so the resync has to cover that shape too:
    a secret left in the index stays searchable long after it is gone from the event."""
    event_bus.emit(NotificationEvent(type="notification", source="whatsapp", summary=f"the key is {SECRET} for backups"))

    redact.scrub(db_conn, [row_id for row_id, _ in redact.scan(db_conn)])

    assert event_bus.search(SECRET) == []
    hits = event_bus.search("backups")
    assert len(hits) == 1
    assert "[REDACTED]" in tp.cast(tp.Any, hits[0])["summary"]


def test_scrub_keeps_blob_valid_json_when_secret_abuts_escaped_quote(event_bus, db_conn):
    # A mongodb URI wrapped in shell double-quotes: the closing quote JSON-encodes to \", so the
    # secret abuts an escape boundary. A raw text .sub over the stored blob splices [REDACTED]
    # across that \" and produces invalid JSON, which breaks the FTS json_extract and rolls the
    # whole scrub back. The JSON-aware scrub redacts the decoded value and re-serializes cleanly.
    event_bus.emit(AssistantEvent(type="assistant", text='mongo "mongodb://user:secretpass@cluster0.example.net/db"'))
    raw = db_conn.execute("SELECT data FROM events").fetchone()[0]
    with pytest.raises(json.JSONDecodeError):
        json.loads(redact.REGEX.sub(redact.mask, raw))

    ids = [row_id for row_id, _ in redact.scan(db_conn)]
    assert redact.scrub(db_conn, ids) == 1

    data = db_conn.execute("SELECT data FROM events").fetchone()[0]
    parsed = json.loads(data)
    assert "secretpass" not in data
    assert "[REDACTED]" in parsed["text"]
    assert event_bus.search("secretpass") == []
    assert len(event_bus.search("mongo")) == 1


def test_scrub_only_touches_the_given_events(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text=f"real leak {SECRET}"))
    event_bus.emit(AssistantEvent(type="assistant", text=f"benign discussion of {SECRET} to keep"))
    rows = list(db_conn.execute("SELECT id FROM events ORDER BY id"))
    keep_id = rows[1][0]

    redact.scrub(db_conn, [rows[0][0]])

    kept = db_conn.execute("SELECT data FROM events WHERE id = ?", (keep_id,)).fetchone()[0]
    assert SECRET in kept


def test_scan_and_scrub_converge_when_secret_reseeds(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text=f"original leak {SECRET}"))
    redact.scrub(db_conn, [row_id for row_id, _ in redact.scan(db_conn)])
    assert redact.scan(db_conn) == []

    event_bus.emit(AssistantEvent(type="assistant", text=f"last night I redacted {SECRET} from history"))
    reseeded = redact.scan(db_conn)
    assert len(reseeded) == 1
    redact.scrub(db_conn, [row_id for row_id, _ in reseeded])
    assert redact.scan(db_conn) == []
    assert all(SECRET not in row[0] for row in db_conn.execute("SELECT data FROM events"))


def test_scrub_is_noop_on_events_without_secrets(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text="nothing sensitive here"))
    row_id = db_conn.execute("SELECT id FROM events").fetchone()[0]

    assert redact.scrub(db_conn, [row_id]) == 0


def test_scan_skips_already_redacted_values(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text=f"password={SECRET}"))
    ids = [row_id for row_id, _ in redact.scan(db_conn)]

    redact.scrub(db_conn, ids)

    assert redact.scan(db_conn) == []


@pytest.mark.parametrize(
    "text",
    [
        "password reuse",
        "secret santa",
        "the api key rotation",
        "please remember your password before you leave",
    ],
)
def test_scan_ignores_benign_prose_with_bare_space(event_bus, db_conn, text):
    event_bus.emit(AssistantEvent(type="assistant", text=text))

    assert redact.scan(db_conn) == []


@pytest.mark.parametrize(
    "text",
    [
        "password=hunter2longvalue",
        "password = hunter2longvalue",
        'api_key = "abcd1234efgh"',
        'password: "supersecretvalue"',
        "password: hunter2value",
        "secret = topsecretvalue",
        '{"password":"supersecretvalue"}',
        'api_key="abcd1234"',
        "PASSWORD:  Tr0ub4dorvalue",
        # A quote separator with the value hard against it: the CLI-flag shape.
        '--password "hunter2xyz"',
        "email-client --password 'appspecificpw'",
        # A value padded inside its quotes, closing quote present, so the leading space is part of
        # the value rather than the gap after a closing quote.
        'password="  hunter2xyz"',
        '--password "  hunter2xyz"',
        "api_key: '  abcd1234efgh'",
    ],
)
def test_scan_catches_space_padded_credential_assignments(event_bus, db_conn, text):
    event_bus.emit(AssistantEvent(type="assistant", text=text))

    matches = redact.scan(db_conn)

    assert len(matches) == 1
    assert "[REDACTED]" in matches[0][1]


@pytest.mark.parametrize(
    "text",
    [
        'the "gmail-app-password" provider',
        'the "app-password" setting stores it',
        'send the "api-key" header always',
        'rotate the "client-secret" quarterly',
        'the "smtp-password" documentation entry',
    ],
)
def test_scan_ignores_quoted_identifier_followed_by_prose(event_bus, db_conn, text):
    """A quote that CLOSES a quoted identifier is not an assignment separator, so the English word
    after it is prose, not a value. These shapes carry no credential at all: the word inside the
    quotes is the identifier and the word after them is ordinary text."""
    event_bus.emit(AssistantEvent(type="assistant", text=text))

    assert redact.scan(db_conn) == []


# Payment-card (PAN) detection: a Luhn-checked pass layered on top of the regex patterns. Well-known
# test PANs, never real cards. Amex is 15 digits (4-6-5 groups), Visa/Mastercard 16 digits.
VISA = "4111111111111111"
AMEX = "378282246310005"


def test_luhn_valid_accepts_real_pans_and_rejects_a_tampered_one():
    assert redact.luhn_valid(VISA)
    assert redact.luhn_valid(AMEX)
    assert redact.luhn_valid("5555555555554444")
    assert not redact.luhn_valid("4111111111111112")


@pytest.mark.parametrize(
    "text",
    [
        f"charge to {VISA} today",
        "card 4111 1111 1111 1111 on file",
        "card 4111-1111-1111-1111 on file",
        f"amex {AMEX} expires soon",
        "amex 3782 822463 10005 expires soon",
        "amex 3782-822463-10005 expires soon",
    ],
)
def test_scan_flags_luhn_valid_cards_with_or_without_separators(text):
    matches = redact.find_matches(text)

    assert len(matches) == 1
    assert VISA not in matches[0] and AMEX not in matches[0]
    assert "4111" not in matches[0] and "3782" not in matches[0]
    assert "[REDACTED]" in matches[0]


@pytest.mark.parametrize(
    "text",
    [
        "order 1234567890123456 shipped",  # 16 digits, fails Luhn: an order number, not a PAN
        "tracking 1234 5678 9012 3456 today",
        "ts 20240101000000 logged",
        "call 15551234567 back",
        # Visa prefix, tampered check digit: keeps Luhn load-bearing now that the IIN gate would
        # reject every other case here on its own.
        "card 4111111111111112 on file",
    ],
)
def test_scan_ignores_non_luhn_digit_runs(text):
    assert redact.find_matches(text) == []


# IIN gate: Luhn alone passes ~1 in 10 non-card digit runs, so a 13-digit epoch-millis id or an order
# number sails through it. The card PANs below are well-known test numbers across the major networks,
# never real cards.
EPOCH_MILLIS = "1785121902428"  # 13-digit notification-id timestamp, passes Luhn by chance
ORDER_16 = "1000000000000008"  # 16-digit order number, passes Luhn but opens with MII 1
MC_2SERIES = "2223003122003222"  # Mastercard 2-series (2221 to 2720)
DISCOVER = "6011111111111117"
JCB = "3530111333300000"


def test_iin_gate_rejects_luhn_passing_non_cards():
    # Both pass Luhn but open with MII 1, so they are timestamps/order ids, not PANs.
    assert redact.luhn_valid(EPOCH_MILLIS) and not redact._is_card(EPOCH_MILLIS)
    assert redact.luhn_valid(ORDER_16) and not redact._is_card(ORDER_16)
    assert redact.find_matches(f"notification {EPOCH_MILLIS} delivered") == []
    assert redact.find_matches(f"order {ORDER_16} shipped") == []


@pytest.mark.parametrize(
    "pan",
    [VISA, AMEX, MC_2SERIES, DISCOVER, JCB],
)
def test_iin_gate_still_flags_real_pans_across_networks(pan):
    assert redact._is_card(pan)
    matches = redact.find_matches(f"charge to {pan} today")
    assert len(matches) == 1
    assert pan not in matches[0]
    assert "[REDACTED]" in matches[0]


def test_scan_still_flags_existing_key_and_jwt_patterns():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    assert len(redact.find_matches("token sk-abcdefghijklmnopqrstuvwxyz1234")) == 1
    assert len(redact.find_matches(f"auth {jwt} header")) == 1


# One case per GitHub token family, so no prefix can silently drop out of the character class.
@pytest.mark.parametrize("prefix", ["ghp_", "gho_", "ghu_", "ghs_", "ghr_"])
def test_scan_flags_every_github_token_prefix(prefix):
    token = prefix + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    matches = redact.find_matches(f"authorization: token {token} sent")

    assert len(matches) == 1
    assert token not in matches[0]
    assert "[REDACTED]" in matches[0]


def test_scan_still_ignores_the_news_slug_false_positive():
    assert redact.find_matches("read sk-hynix-raises-full-year-guidance-on-ai-demand today") == []


# Namespaced identifiers: the digit run is the tail of a dotted id, not a PAN. These clear both the
# IIN gate and Luhn, so the dot in the lookbehind is the only thing separating them from a card.
NAMESPACED_IDS = ["mdp.39015017012900", "coo.31924002274110", "inu.30000047482611"]


@pytest.mark.parametrize("ident", NAMESPACED_IDS)
def test_namespaced_identifiers_are_not_read_as_cards(ident):
    digits = ident.split(".", 1)[1]
    # Guard: without the namespace these WOULD be flagged, so the test cannot pass by accident.
    assert redact.luhn_valid(digits) and redact._has_card_iin(digits) and redact._is_card(digits)
    assert redact.find_matches(f"fetch id={ident} now") == []
    assert redact.redact_cards(ident) == ident


def test_namespace_rejection_needs_the_dot_adjacent():
    # A PAN after a sentence-ending period is still a PAN: the separating space breaks the binding.
    assert redact.find_matches(f"paid. {VISA} cleared") != []
    # And a PAN quoted or assigned normally is untouched by the change.
    assert redact.find_matches(f'card="{VISA}"') != []


def test_pan_glued_to_a_period_is_the_accepted_false_negative():
    # A PAN hard against a sentence-ending period is indistinguishable from a namespaced id, so the
    # dot lookbehind skips it. Accepted: a real PAN follows a space, a colon or a quote.
    assert redact.find_matches(f"Done.{VISA}") == []


def test_card_scan_is_idempotent_on_already_redacted_text():
    assert redact.find_matches(f"charge to {VISA} today") != []
    assert redact.find_matches("charge to [REDACTED] today") == []


def test_scrub_redacts_a_card_in_place_and_keeps_valid_json(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text=f"paid with {VISA} last night"))
    ids = sorted({row_id for row_id, _ in redact.scan(db_conn)})

    assert redact.scrub(db_conn, ids) == 1

    data = db_conn.execute("SELECT data FROM events").fetchone()[0]
    json.loads(data)  # still valid JSON after the in-place scrub
    assert VISA not in data
    assert "paid with [REDACTED] last night" in json.loads(data)["text"]
    assert redact.scan(db_conn) == []  # converges: a second scan finds nothing


def test_main_scan_then_scrub_end_to_end(tmp_path, event_bus, db_conn, monkeypatch, capsys):
    event_bus.emit(AssistantEvent(type="assistant", text=f"my key is {SECRET}"))
    event_bus.emit(AssistantEvent(type="assistant", text="just a normal message"))
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")

    monkeypatch.setattr("sys.argv", ["redact_secrets.py"])
    assert redact.main() == 0
    out = capsys.readouterr().out
    assert "Found 1 event(s)" in out
    assert SECRET not in out
    leak_id = int(out.splitlines()[-1].split("|", 1)[0])

    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--scrub", str(leak_id)])
    assert redact.main() == 0
    assert "Scrubbed secrets in 1 event(s)" in capsys.readouterr().out

    rows = [row[0] for row in db_conn.execute("SELECT data FROM events")]
    assert len(rows) == 2
    assert all(SECRET not in data for data in rows)


# ---------------------------------------------------------------------------
# --show: one event's full data, every detected secret masked
# ---------------------------------------------------------------------------


def test_main_show_prints_the_full_event_with_the_secret_masked(tmp_path, event_bus, db_conn, monkeypatch, capsys):
    event_bus.emit(AssistantEvent(type="assistant", text=f"a long surrounding message where the aws key is {SECRET} for backups"))
    row_id = db_conn.execute("SELECT id FROM events").fetchone()[0]
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--show", str(row_id)])

    assert redact.main() == 0

    out = capsys.readouterr().out
    assert SECRET not in out
    assert "[REDACTED]" in out
    assert "a long surrounding message" in out and "for backups" in out


def test_main_show_unknown_id_errors_on_stderr(tmp_path, event_bus, monkeypatch, capsys):
    event_bus.emit(AssistantEvent(type="assistant", text="anything"))
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--show", "999999"])

    assert redact.main() != 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "999999" in captured.err


def test_main_show_rejects_a_non_numeric_id_with_usage_on_stderr(tmp_path, event_bus, monkeypatch, capsys):
    event_bus.emit(AssistantEvent(type="assistant", text="anything"))
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--show", "not-an-id"])

    assert redact.main() != 0
    assert "usage:" in capsys.readouterr().err


def _insert_raw_event(conn, payload: dict) -> int:
    cursor = conn.execute("INSERT INTO events (ts, data) VALUES ('2026-01-01T00:00:00', ?)", (json.dumps(payload),))
    conn.commit()
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Vendor token prefixes
# ---------------------------------------------------------------------------
# Each prefix is anchored case-sensitively. Under the module's outer IGNORECASE a short lowercase
# prefix also matches its own letters inside base64url runs (reasoning-block signatures, media
# keys), and the scan output is uncapped, so that noise buries real rows.

VENDOR_TOKENS = [
    "hf_" + "a" * 34,
    "tfp_" + "b" * 44,
    "napi_" + "c" * 24,
    "dckr_pat_" + "d" * 24,
    "sbp_" + "e" * 40,
    "shpat_" + "f" * 32,
    "lin_api_" + "g" * 24,
    "wak_" + "h" * 24,
]


@pytest.mark.parametrize("token", VENDOR_TOKENS)
def test_scan_flags_vendor_prefixed_tokens(token):
    matches = redact.find_matches(f"curl -H 'Authorization: {token}' https://api.example.com")

    assert len(matches) == 1
    assert token not in matches[0]
    assert "[REDACTED]" in matches[0]


@pytest.mark.parametrize("token", VENDOR_TOKENS)
def test_vendor_prefixes_are_case_anchored(token):
    # The same body behind an upper-cased prefix is not a real key of any of these vendors, so it
    # must not match: this is exactly the base64url-run false positive the anchoring exists to stop.
    prefix, _, body = token.partition("_")
    assert redact.find_matches(f"blob {prefix.upper()}_{body} end") == []


def test_vendor_prefixes_survive_the_scrub_round_trip(event_bus, db_conn):
    token = "hf_" + "z" * 34
    event_bus.emit(AssistantEvent(type="assistant", text=f"huggingface-cli login --token {token}"))
    ids = sorted({row_id for row_id, _ in redact.scan(db_conn)})

    assert redact.scrub(db_conn, ids) == 1

    rows = [row[0] for row in db_conn.execute("SELECT data FROM events")]
    assert all(token not in data for data in rows)
    assert all(json.loads(data) for data in rows)


def test_scan_flags_github_app_installation_tokens(event_bus, db_conn):
    # ghs_<installation-id>_<jwt> carries underscores and dots inside the body, and a truncated
    # copy (piped through head) must still match on length alone.
    token = "ghs_12345678_" + "a1" * 20
    event_bus.emit(AssistantEvent(type="assistant", text=f"auth with {token} now"))

    matches = redact.scan(db_conn)

    assert len(matches) == 1
    assert token not in matches[0][1]


# Secrets named by an arbitrary key name, a hyphenated header, the auth scheme, or a URL position.
# The literal-word pattern only knows password/secret/api_key, so the shapes a key actually arrives
# in (EXA_KEY=..., an X-Plex-Token: header, a JSON "token" field, Bearer, a ?sig= query value, a
# bare /api/<key> path segment) need their own rules.


@pytest.mark.parametrize(
    "text",
    [
        "EXA_KEY=abcd1234efgh5678ijkl curl https://api.example.com",
        "GH_TOKEN=abcd1234efgh5678ijkl gh pr list",
        'curl -H "X-Plex-Token: abcd1234efgh5678ijkl" http://plex.local',
        '{"token": "abcd1234efgh5678ijkl"}',
        'curl -H "Authorization: Bearer abcd1234efgh5678ijkl" https://api.github.com',
        "https://cdn.example.com/file?sig=abc123def456ghi789",
        "https://192.168.1.10/api/q1w2e3r4t5q1w2e3r4t5q1w2e3r4t5/lights",
    ],
)
def test_scan_catches_named_urlborne_and_bearer_secrets(event_bus, db_conn, text):
    event_bus.emit(AssistantEvent(type="assistant", text=text))

    matches = redact.scan(db_conn)

    assert len(matches) == 1
    assert "[REDACTED]" in matches[0][1]


@pytest.mark.parametrize(
    "text",
    [
        # No digit anywhere in the value: prose and identifier-ish assignments, not credentials.
        "PRIMARY_KEY=customer_account_number",
        "the key = a good one for this problem",
        "sort_key: alphabetical_ordering",
        # Too short to be a credential.
        "token=abc123",
        # The scheme without a plausible value.
        "Bearer with us while this deploys",
        # A camelCase docs URL: 25+ chars after /api/ but no digit, so the path rule stays quiet.
        "https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnectionIceEvent",
    ],
)
def test_scan_ignores_named_separators_that_are_not_credentials(event_bus, db_conn, text):
    event_bus.emit(AssistantEvent(type="assistant", text=text))

    assert redact.scan(db_conn) == []


@pytest.mark.parametrize("run", ["A1b2" * 100_000, "http://x" * 100_000])
def test_scan_stays_linear_on_long_unbroken_runs(run):
    # Quantified prefixes backtrack quadratically on exactly these inputs (a quantified name-prefix
    # in the named-key rule on base64 reasoning signatures, a quantified URL prefix in the /api/
    # rule on scheme-dense text); the literal-anchored rules scan them in linear time, so this
    # completes in well under a second instead of hanging the suite.
    assert redact.find_matches(run) == []


# ---------------------------------------------------------------------------
# Scrub verification: the committed rows are checked, not the writer's word
# ---------------------------------------------------------------------------


def test_scrub_verification_stays_quiet_on_a_complete_scrub(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text=f"the aws key is {SECRET} for backups"))
    ids = sorted({row_id for row_id, _ in redact.scan(db_conn)})
    hits = redact.stored_hits(db_conn, ids)

    redact.scrub(db_conn, ids)

    assert redact.still_matching(db_conn, hits) == []
    stored = db_conn.execute("SELECT data FROM events").fetchone()[0]
    assert SECRET not in stored


def test_scrub_redacts_a_secret_used_as_a_json_key(db_conn):
    # An object KEY can hold the secret; a rewrite that only walks values leaves it in the
    # committed row, so keys go through the same redaction pass.
    row_id = _insert_raw_event(db_conn, {"type": "note", SECRET: "context for the key"})

    assert redact.scrub(db_conn, [row_id]) == 1

    stored = db_conn.execute("SELECT data FROM events WHERE id = ?", (row_id,)).fetchone()[0]
    assert SECRET not in stored
    assert "[REDACTED]" in json.loads(stored)


def test_scrub_warns_when_a_matched_hit_survives_the_rewrite(db_conn, tmp_path, monkeypatch, capsys):
    """A payment card stored as a JSON NUMBER is matched by the scan (which reads the raw blob) but
    sits outside every string the rewrite touches, so the committed row still holds it: the scrub
    must report that and exit 2 instead of claiming success."""
    row_id = _insert_raw_event(db_conn, {"type": "note", "amount": int(VISA)})
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--scrub", str(row_id)])

    assert redact.main() == 2

    out = capsys.readouterr().out
    assert "WARNING" in out and str(row_id) in out
    assert "--scrub-literal" in out


# ---------------------------------------------------------------------------
# --scrub-literal: redact one known value the scanner cannot detect
# ---------------------------------------------------------------------------

# A password a human chose: no prefix, low entropy, matches none of the scanner's API-key shapes.
UNDETECTABLE = "correct-horse-battery-staple"


def test_scanner_cannot_detect_a_human_chosen_password(event_bus, db_conn):
    # The premise of --scrub-literal: --scrub is pattern-driven, so a value the scanner misses is
    # one --scrub can never remove, even with the exact event ids in hand.
    event_bus.emit(AssistantEvent(type="assistant", text=f"the login is {UNDETECTABLE} for now"))
    ids = [row_id for row_id, _ in db_conn.execute("SELECT id, data FROM events")]

    assert redact.scan(db_conn) == []
    assert redact.scrub(db_conn, ids) == 0
    assert UNDETECTABLE in db_conn.execute("SELECT data FROM events").fetchone()[0]


def test_scrub_literal_removes_every_stored_copy(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text=f"first {UNDETECTABLE}"))
    event_bus.emit(AssistantEvent(type="assistant", text=f"again {UNDETECTABLE} and {UNDETECTABLE}"))
    event_bus.emit(AssistantEvent(type="assistant", text="unrelated message"))

    assert redact.scrub_literal(db_conn, UNDETECTABLE) == (2, 0)

    rows = [row[0] for row in db_conn.execute("SELECT data FROM events")]
    assert all(UNDETECTABLE not in data for data in rows)
    assert redact.count_literal(db_conn, UNDETECTABLE) == 0


def test_scrub_literal_reaches_a_value_used_as_a_json_key(db_conn):
    row_id = _insert_raw_event(db_conn, {"type": "note", UNDETECTABLE: "x"})

    assert redact.scrub_literal(db_conn, UNDETECTABLE) == (1, 0)

    stored = db_conn.execute("SELECT data FROM events WHERE id = ?", (row_id,)).fetchone()[0]
    assert UNDETECTABLE not in stored


def test_scrub_literal_keeps_fts_in_sync(event_bus, db_conn):
    # The bug this guards: a plain UPDATE leaves the pre-scrub text (secret included) searchable,
    # because events_fts is external-content with insert/delete triggers only.
    event_bus.emit(AssistantEvent(type="assistant", text=f"password {UNDETECTABLE} for the account"))
    assert event_bus.search(f'"{UNDETECTABLE}"') != []  # searchable before, so the check below bites

    redact.scrub_literal(db_conn, UNDETECTABLE)

    assert event_bus.search(f'"{UNDETECTABLE}"') == []  # quoted: FTS reads a bare hyphen as an operator
    hits = event_bus.search("account")
    assert len(hits) == 1
    assert "[REDACTED]" in hits[0]["text"]


def test_scrub_literal_handles_a_secret_abutting_an_escaped_quote(event_bus, db_conn):
    # Same escape-boundary hazard as the pattern scrub: replacing on the serialized blob would
    # splice [REDACTED] across the encoded quote and produce invalid JSON.
    event_bus.emit(AssistantEvent(type="assistant", text=f'login "{UNDETECTABLE}" now'))

    assert redact.scrub_literal(db_conn, UNDETECTABLE) == (1, 0)

    data = db_conn.execute("SELECT data FROM events").fetchone()[0]
    assert json.loads(data)["text"] == 'login "[REDACTED]" now'


def test_scrub_literal_reports_a_number_held_copy_it_cannot_reach(db_conn):
    """A digits-only value stored as a bare JSON number sits outside every string the rewrite
    touches; the verification counts it from the raw blob, so the result is never a false clean."""
    _insert_raw_event(db_conn, {"type": "note", "amount": 123456789012})

    assert redact.scrub_literal(db_conn, "123456789012") == (0, 1)


def test_main_scrub_literal_exits_2_when_a_copy_is_unreachable(tmp_path, event_bus, db_conn, monkeypatch, capsys):
    _insert_raw_event(db_conn, {"type": "note", "amount": 123456789012})
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--scrub-literal", "123456789012"])

    assert redact.main() == 2

    out = capsys.readouterr().out
    assert "1 remain" in out
    assert "by hand" in out


def test_scrub_literal_leaves_events_without_the_value_untouched(event_bus, db_conn):
    event_bus.emit(AssistantEvent(type="assistant", text="a message with no secret in it"))
    before = db_conn.execute("SELECT data FROM events").fetchone()[0]

    assert redact.scrub_literal(db_conn, UNDETECTABLE) == (0, 0)

    assert db_conn.execute("SELECT data FROM events").fetchone()[0] == before


def test_main_scrub_literal_never_echoes_the_value(tmp_path, event_bus, db_conn, monkeypatch, capsys):
    event_bus.emit(AssistantEvent(type="assistant", text=f"the login is {UNDETECTABLE}"))
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--scrub-literal", UNDETECTABLE])

    assert redact.main() == 0

    out = capsys.readouterr().out
    assert UNDETECTABLE not in out
    assert "Scrubbed 1 event(s); 0 remain" in out
    assert f"length {len(UNDETECTABLE)}" in out
    assert UNDETECTABLE not in db_conn.execute("SELECT data FROM events").fetchone()[0]


def test_main_scrub_literal_rejects_a_missing_value(tmp_path, event_bus, monkeypatch, capsys):
    event_bus.emit(AssistantEvent(type="assistant", text="anything"))
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--scrub-literal"])

    assert redact.main() == 1
    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert captured.out == ""


def test_main_scrub_literal_refuses_a_short_literal(tmp_path, event_bus, monkeypatch, capsys):
    # The rewrite is DB-wide: a tiny literal would splice the placeholder through unrelated text.
    event_bus.emit(AssistantEvent(type="assistant", text="the pin is 12345 today"))
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--scrub-literal", "12345"])

    assert redact.main() == 1
    captured = capsys.readouterr()
    assert "Refusing" in captured.err
    assert captured.out == ""


def test_main_scrub_explains_a_zero_event_result(tmp_path, event_bus, db_conn, monkeypatch, capsys):
    # A 0 that reads like "those events were clean" is the failure mode: point at the other mode.
    event_bus.emit(AssistantEvent(type="assistant", text=f"the login is {UNDETECTABLE}"))
    leak_id = db_conn.execute("SELECT id FROM events").fetchone()[0]
    monkeypatch.setattr(redact, "DB", tmp_path / "events.db")
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--scrub", str(leak_id)])

    assert redact.main() == 0

    out = capsys.readouterr().out
    assert "Scrubbed secrets in 0 event(s)" in out
    assert "does NOT mean they were clean" in out
    assert "--scrub-literal" in out


def test_wrapper_behaves_the_same_whatever_the_caller_cwd(tmp_path):
    """The wrapper cds to its own directory before exec, so interpreter resolution (which walks up
    from the caller's cwd) is identical wherever the caller sits. HOME is redirected so both runs
    take the cheap, deterministic "No database at" path."""
    scripts = SCRIPT.parent
    wrapper = scripts / "redact_secrets.sh"
    env = {**os.environ, "HOME": str(tmp_path)}

    runs = [
        subprocess.run(["sh", str(wrapper)], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120, check=False)
        for cwd in (tmp_path, scripts)
    ]

    assert runs[0].stdout == runs[1].stdout
    assert runs[0].returncode == runs[1].returncode
    assert all("No database at" in run.stderr for run in runs)
