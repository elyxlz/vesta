"""Tests for the dream skill's redact_secrets script: masked pattern scan + in-place scrub by id."""

import importlib.util
import pathlib as pl
import sqlite3

import pytest

from core.events import ChatEvent, UserEvent

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
    event_bus.emit(ChatEvent(type="chat", text=f"the aws key is {SECRET} for backups"))

    matches = redact.scan(db_conn)

    assert len(matches) == 1
    _, snippet = matches[0]
    assert SECRET not in snippet
    assert "[REDACTED]" in snippet
    assert "the aws key is" in snippet and "for backups" in snippet


def test_scan_reports_every_match_in_an_event(event_bus, db_conn):
    event_bus.emit(ChatEvent(type="chat", text="first AKIAABCDEFGHIJKLMNOP then xoxb-1234-abcdef in one message"))

    matches = redact.scan(db_conn)

    assert len(matches) == 2
    assert all("AKIA" not in snippet and "xoxb-1234" not in snippet for _, snippet in matches)


def test_scrub_redacts_the_secret_in_place_and_keeps_context(event_bus, db_conn):
    event_bus.emit(ChatEvent(type="chat", text=f"leaked {SECRET} during backup"))
    ids = sorted({row_id for row_id, _ in redact.scan(db_conn)})

    assert redact.scrub(db_conn, ids) == 1

    data = db_conn.execute("SELECT data FROM events").fetchone()[0]
    assert SECRET not in data
    assert "leaked [REDACTED] during backup" in data


def test_scrub_keeps_fts_in_sync(event_bus, db_conn):
    event_bus.emit(ChatEvent(type="chat", text=f"leaked {SECRET} during backup"))

    redact.scrub(db_conn, [row_id for row_id, _ in redact.scan(db_conn)])

    assert event_bus.search(SECRET) == []
    hits = event_bus.search("backup")
    assert len(hits) == 1
    assert "[REDACTED]" in hits[0]["text"]

    db_conn.execute("DELETE FROM events")
    db_conn.commit()
    assert event_bus.search("backup") == []


def test_scrub_only_touches_the_given_events(event_bus, db_conn):
    event_bus.emit(ChatEvent(type="chat", text=f"real leak {SECRET}"))
    event_bus.emit(ChatEvent(type="chat", text=f"benign discussion of {SECRET} to keep"))
    rows = list(db_conn.execute("SELECT id FROM events ORDER BY id"))
    keep_id = rows[1][0]

    redact.scrub(db_conn, [rows[0][0]])

    kept = db_conn.execute("SELECT data FROM events WHERE id = ?", (keep_id,)).fetchone()[0]
    assert SECRET in kept


def test_scan_and_scrub_converge_when_secret_reseeds(event_bus, db_conn):
    event_bus.emit(ChatEvent(type="chat", text=f"original leak {SECRET}"))
    redact.scrub(db_conn, [row_id for row_id, _ in redact.scan(db_conn)])
    assert redact.scan(db_conn) == []

    event_bus.emit(ChatEvent(type="chat", text=f"last night I redacted {SECRET} from history"))
    reseeded = redact.scan(db_conn)
    assert len(reseeded) == 1
    redact.scrub(db_conn, [row_id for row_id, _ in reseeded])
    assert redact.scan(db_conn) == []
    assert all(SECRET not in row[0] for row in db_conn.execute("SELECT data FROM events"))


def test_scrub_is_noop_on_events_without_secrets(event_bus, db_conn):
    event_bus.emit(ChatEvent(type="chat", text="nothing sensitive here"))
    row_id = db_conn.execute("SELECT id FROM events").fetchone()[0]

    assert redact.scrub(db_conn, [row_id]) == 0


def test_scan_skips_already_redacted_values(event_bus, db_conn):
    event_bus.emit(ChatEvent(type="chat", text=f"password={SECRET}"))
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
    event_bus.emit(ChatEvent(type="chat", text=text))

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
    event_bus.emit(ChatEvent(type="chat", text=text))

    matches = redact.scan(db_conn)

    assert len(matches) == 1
    assert "[REDACTED]" in matches[0][1]


def test_main_scan_then_scrub_end_to_end(tmp_path, event_bus, db_conn, monkeypatch, capsys):
    event_bus.emit(ChatEvent(type="chat", text=f"my key is {SECRET}"))
    event_bus.emit(UserEvent(type="user", text="just a normal message"))
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
