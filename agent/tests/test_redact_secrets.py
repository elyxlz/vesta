"""Tests for the dream skill's redact_secrets script: masked pattern scan + in-place scrub by id."""

import importlib.util
import json
import pathlib as pl
import sqlite3

import pytest

from core.events import AssistantEvent

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
    ],
)
def test_scan_catches_space_padded_credential_assignments(event_bus, db_conn, text):
    event_bus.emit(AssistantEvent(type="assistant", text=text))

    matches = redact.scan(db_conn)

    assert len(matches) == 1
    assert "[REDACTED]" in matches[0][1]


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


def test_scan_still_ignores_the_news_slug_false_positive():
    assert redact.find_matches("read sk-hynix-raises-full-year-guidance-on-ai-demand today") == []


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


# Secrets named by an arbitrary key name, a hyphenated header, or the auth scheme.
# The literal-word pattern only knows password/secret/api_key, so the shapes a key actually arrives
# in were invisible: EXA_KEY=..., an X-Plex-Token: header, a JSON "token" field, and Bearer, where
# the scheme names the secret. Against a 205k-event store these added 76 real credentials.


@pytest.mark.parametrize(
    "text",
    [
        "EXA_KEY=abcd1234efgh5678ijkl curl https://api.example.com",
        "GH_TOKEN=abcd1234efgh5678ijkl gh pr list",
        'curl -H "X-Plex-Token: abcd1234efgh5678ijkl" http://plex.local',
        'curl -H "X-Agent-Token: abcd1234efgh5678ijkl" http://127.0.0.1',
        '{"token": "abcd1234efgh5678ijkl"}',
        'curl -H "Authorization: Bearer abcd1234efgh5678ijkl" https://api.github.com',
    ],
)
def test_scan_catches_named_separator_and_bearer_secrets(event_bus, db_conn, text):
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
    ],
)
def test_scan_ignores_named_separators_that_are_not_credentials(event_bus, db_conn, text):
    event_bus.emit(AssistantEvent(type="assistant", text=text))

    assert redact.scan(db_conn) == []
