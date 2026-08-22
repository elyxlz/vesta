"""Tests for contacts/scripts/live-channel.sh.

The property under test is not "does it print a number". It is that the script never prints a
number it did not measure, and that its degraded mode errs toward MORE silence rather than less.
A silence figure is used to ration work, so an unreadable store that reports "0 hours since they
wrote" makes the rationing inert everywhere and looks healthy while doing it.
"""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/contacts/scripts/live-channel.sh"


def _events_db(path: Path, rows: list[tuple[str, str, str | None]]) -> Path:
    """Build an events store in the shape core actually emits. Each row is (ts, source, sender).

    The payload mirrors `loops.py`'s notification emit exactly: `sender` is the normalized identity
    written by `notif_sender()`, and `fields` is `notif_facet_fields()`, which EXCLUDES every
    identity field by construction. So the sender's name appears in `sender` and nowhere else.

    An earlier version of this file invented `body='contact_name="..."'`, a shape the emit path
    never produces. Every test passed against it while the script was broken on every real box,
    which is the whole reason this docstring is here: a fixture built from the code under test can
    only prove the code agrees with itself.
    """
    db = path / "events.db"
    con = sqlite3.connect(db)
    con.execute("create table events (ts text, data text)")
    for ts, source, name in rows:
        payload: dict[str, object] = {
            "type": "notification",
            "source": source,
            "summary": f'<channel source="{source}" />',
            "notif_type": "message",
            "sender": name or "",
            "fields": {},
            "decided": "interrupt",
        }
        con.execute("insert into events values (?, ?)", (ts, json.dumps(payload)))
    con.commit()
    con.close()
    return db


def _run(db: Path | str, *args: str, owner: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "VESTA_EVENTS_DB": str(db)}
    if owner is not None:
        env["VESTA_OWNER"] = owner
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60, check=False)


def test_missing_store_is_unmeasured_not_zero(tmp_path: Path) -> None:
    r = _run(tmp_path / "absent.db", "--silence-hours", owner="sam")
    assert r.stdout.strip() == "UNMEASURED"
    assert r.returncode == 2


def test_present_but_empty_store_is_unmeasured(tmp_path: Path) -> None:
    """An unwritten store is not a quiet user. This is the case that most looks like health."""
    db = _events_db(tmp_path, [])
    r = _run(db, "--silence-hours", owner="sam")
    assert r.stdout.strip() == "UNMEASURED"
    assert r.returncode == 2


def test_no_owner_inbound_at_all_is_unmeasured(tmp_path: Path) -> None:
    db = _events_db(tmp_path, [("2026-01-01T00:00:00Z", "whatsapp", "someone-else")])
    r = _run(db, "--silence-hours", owner="sam")
    assert r.stdout.strip() == "UNMEASURED"
    assert r.returncode == 2


def test_named_owner_inbound_yields_an_integer(tmp_path: Path) -> None:
    db = _events_db(tmp_path, [("2026-01-01T00:00:00Z", "whatsapp", "sam")])
    r = _run(db, "--silence-hours", owner="sam")
    assert r.stdout.strip().isdigit()
    assert r.returncode == 0


def test_app_chat_needs_no_owner_name(tmp_path: Path) -> None:
    """app-chat is the owner's own screen, so inbound there is theirs by construction."""
    db = _events_db(tmp_path, [("2026-01-01T00:00:00Z", "app-chat", None)])
    r = _run(db, "--silence-hours")
    assert r.stdout.strip().isdigit()
    assert r.returncode == 0


def test_unnamed_fallback_never_under_reports_silence(tmp_path: Path) -> None:
    """The safety property.

    Owner wrote on app-chat long ago and on a named channel recently. Without a name to match,
    only the app-chat event is attributable, so the answer must be the LARGER silence. Reporting
    the recent one would require guessing that the WhatsApp sender was the owner, and guessing
    wrong there under-reports silence, which is the direction that fails silently.
    """
    db = _events_db(
        tmp_path,
        [
            ("2026-01-01T00:00:00Z", "app-chat", None),
            ("2026-06-01T00:00:00Z", "whatsapp", "sam"),
        ],
    )
    with_name = _run(db, "--silence-hours", owner="sam")
    without_name = _run(db, "--silence-hours")
    assert with_name.stdout.strip().isdigit()
    assert without_name.stdout.strip().isdigit()
    assert int(without_name.stdout) > int(with_name.stdout)


def test_services_are_not_listed_as_contacts(tmp_path: Path) -> None:
    """An inbound with no contact name, from anything but app-chat, is a service reporting in.

    Listed, it renders as a contact called "?" carrying a LIVE channel, which invites a send to
    somewhere nobody is reading. A denylist of machine source names would be box-specific and
    always one skill out of date; absence of a name is a property of the event itself.
    """
    db = _events_db(
        tmp_path,
        [
            ("2026-01-01T00:00:00Z", "reminders", None),
            ("2026-01-02T00:00:00Z", "whatsapp", "sam"),
        ],
    )
    r = _run(db, owner="sam")
    assert "sam" in r.stdout.lower()
    assert "?:" not in r.stdout
    assert "reminders" in r.stdout  # named in the dropped-sources line, not as a contact


def test_unknown_contact_does_not_claim_silence(tmp_path: Path) -> None:
    db = _events_db(tmp_path, [("2026-01-01T00:00:00Z", "whatsapp", "sam")])
    r = _run(db, "nobody-by-that-name", owner="sam")
    assert r.returncode == 1
    assert "not proof they are silent" in r.stderr


@pytest.mark.parametrize("source", ["core", "tasks", "vestad"])
def test_machine_sources_never_count_as_owner_inbound(tmp_path: Path, source: str) -> None:
    db = _events_db(tmp_path, [("2026-01-01T00:00:00Z", source, "sam")])
    r = _run(db, "--silence-hours", owner="sam")
    assert r.stdout.strip() == "UNMEASURED"
