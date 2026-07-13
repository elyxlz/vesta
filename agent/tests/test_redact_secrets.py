"""Tests for the dream skill's redact_secrets script: known-literal scrub + pattern scan."""

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

SECRET = "hunter2secret9000"


@pytest.fixture
def known_file(tmp_path, monkeypatch):
    path = tmp_path / "redact_known.txt"
    monkeypatch.setattr(redact, "KNOWN_FILE", str(path))
    return path


@pytest.fixture
def db_conn(tmp_path, event_bus):
    conn = sqlite3.connect(str(tmp_path / "events.db"))
    yield conn
    conn.close()


def test_scrub_replaces_literal_in_every_event_and_keeps_context(event_bus, db_conn, known_file):
    event_bus.emit(ChatEvent(type="chat", text=f"the password is {SECRET} for gmail"))
    event_bus.emit(UserEvent(type="user", text=f"I found {SECRET} again while cleaning up"))
    known_file.write_text(f"{SECRET}\n")

    assert redact.scrub_known(db_conn) == 2

    rows = [row[0] for row in db_conn.execute("SELECT data FROM events")]
    assert all(SECRET not in data for data in rows)
    assert any("the password is [REDACTED] for gmail" in data for data in rows)


def test_scrub_keeps_fts_in_sync(event_bus, db_conn, known_file):
    event_bus.emit(ChatEvent(type="chat", text=f"leaked {SECRET} during backup"))
    known_file.write_text(f"{SECRET}\n")

    redact.scrub_known(db_conn)

    assert event_bus.search(SECRET) == []
    hits = event_bus.search("backup")
    assert len(hits) == 1
    assert "[REDACTED]" in hits[0]["text"]

    db_conn.execute("DELETE FROM events")
    db_conn.commit()
    assert event_bus.search("backup") == []


def test_scrub_converges_when_secret_reseeds(event_bus, db_conn, known_file):
    event_bus.emit(ChatEvent(type="chat", text=f"original leak {SECRET}"))
    known_file.write_text(f"{SECRET}\n")
    assert redact.scrub_known(db_conn) == 1

    event_bus.emit(ChatEvent(type="chat", text=f"last night I redacted {SECRET} from history"))
    assert redact.scrub_known(db_conn) == 1
    rows = [row[0] for row in db_conn.execute("SELECT data FROM events")]
    assert all(SECRET not in data for data in rows)


def test_scrub_without_known_file_is_noop(event_bus, db_conn, known_file):
    event_bus.emit(ChatEvent(type="chat", text=f"leak {SECRET}"))
    assert redact.scrub_known(db_conn) == 0


def test_scrub_ignores_comments_and_blank_lines(event_bus, db_conn, known_file):
    event_bus.emit(ChatEvent(type="chat", text=f"leak {SECRET}"))
    known_file.write_text(f"# known leaked literals\n\n{SECRET}\n")
    assert redact.scrub_known(db_conn) == 1


def test_scan_reports_every_match_in_an_event(event_bus, db_conn):
    event_bus.emit(ChatEvent(type="chat", text="first AKIAABCDEFGHIJKLMNOP then xoxb-1234-abcdef in one message"))

    matches = redact.scan(db_conn)

    snippets = [snippet for _, snippet in matches]
    assert len(matches) == 2
    assert any("AKIAABCDEFGHIJKLMNOP" in snippet for snippet in snippets)
    assert any("xoxb-1234-abcdef" in snippet for snippet in snippets)


def test_scan_skips_scrubbed_values(event_bus, db_conn, known_file):
    event_bus.emit(ChatEvent(type="chat", text=f"password={SECRET}"))
    known_file.write_text(f"{SECRET}\n")

    assert len(redact.scan(db_conn)) == 1
    redact.scrub_known(db_conn)
    assert redact.scan(db_conn) == []


def test_main_delete_purges_flagged_events(tmp_path, event_bus, db_conn, known_file, monkeypatch, capsys):
    event_bus.emit(ChatEvent(type="chat", text="my key is AKIAABCDEFGHIJKLMNOP"))
    event_bus.emit(ChatEvent(type="chat", text="nothing sensitive here"))
    monkeypatch.setattr(redact, "DB", str(tmp_path / "events.db"))
    monkeypatch.setattr("sys.argv", ["redact_secrets.py", "--delete"])

    assert redact.main() == 0

    out = capsys.readouterr().out
    assert "Found 1 events" in out
    assert "Deleted 1 events." in out
    remaining = [row[0] for row in db_conn.execute("SELECT data FROM events")]
    assert len(remaining) == 1
    assert "nothing sensitive" in remaining[0]
