"""Every email notification carries what else arrived recently.

The incident: on 5 Aug 2026 a landlord sent an e-signature request at 15:16 and a plain covering
email explaining it at 15:19. The agent got a notification for the first, acted on it alone, and had
to retract four minutes later after reading the second. Both were already in the inbox. The two
shared no sender and no domain, so a same-sender heuristic would not have helped.
"""

import json
import time

import pytest
from email_client import poll_daemon as pd


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    notif = tmp_path / "notifications"
    monkeypatch.setattr(pd, "NOTIF_DIR", notif)
    monkeypatch.setattr(pd, "RECENT_PATH", tmp_path / "recent-notifications.json")
    return notif


def _meta(uid, frm, subject):
    return {"uid": uid, "from": frm, "to": "nour@example.com", "subject": subject, "date": "Wed, 5 Aug 2026"}


def _notifs(notif_dir):
    return [json.loads(p.read_text()) for p in sorted(notif_dir.glob("*.json"))]


def _notif(notif_dir, uid):
    # Filenames tie on the millisecond under fast writes, so tests pick by uid, never by glob order.
    (found,) = [n for n in _notifs(notif_dir) if n["uid"] == uid]
    return found


def test_first_notification_has_empty_context(dirs):
    pd.write_notification("personal", "INBOX", _meta("1", "a@x.com", "hello"))
    (sent,) = _notifs(dirs)
    assert sent["also_arrived_recently"] == []


def test_the_grainger_case(dirs):
    """Different senders, different domains, three minutes apart. The second must be visible."""
    esign_subject = "Acknowledgement requested on 3D Webber Street | Section 13"
    pd.write_notification("personal", "INBOX", _meta("204516", "Jemma via Adobe Sign <adobesign@adobesign.com>", esign_subject))
    pd.write_notification(
        "personal", "INBOX", _meta("204519", "Jemma Herring <jherring@graingerplc.co.uk>", "3D Webber Street | Tenancy Review")
    )
    second = _notif(dirs, "204519")
    context = second["also_arrived_recently"]
    assert len(context) == 1
    assert context[0]["uid"] == "204516"
    assert "Section 13" in context[0]["subject"]
    # No relatedness matching is claimed or required: the senders share nothing.
    assert "adobesign" in context[0]["from"]


def test_newest_first_and_capped(dirs):
    for i in range(pd.RECENT_SHOW + 4):
        pd.write_notification("personal", "INBOX", _meta(str(i), f"s{i}@x.com", f"subject {i}"))
    last = _notif(dirs, str(pd.RECENT_SHOW + 3))
    context = last["also_arrived_recently"]
    assert len(context) == pd.RECENT_SHOW
    # Newest first: the immediately preceding message leads.
    assert context[0]["subject"] == f"subject {pd.RECENT_SHOW + 2}"


def test_entries_older_than_the_window_drop_out(dirs, monkeypatch):
    pd.write_notification("personal", "INBOX", _meta("1", "old@x.com", "ancient"))
    real_time = time.time
    monkeypatch.setattr(pd.time, "time", lambda: real_time() + pd.RECENT_WINDOW_SECS + 60)
    pd.write_notification("personal", "INBOX", _meta("2", "new@x.com", "fresh"))
    assert _notifs(dirs)[1]["also_arrived_recently"] == []


def test_accounts_do_not_leak_into_each_other(dirs):
    pd.write_notification("work", "INBOX", _meta("1", "boss@work.com", "work thing"))
    pd.write_notification("personal", "INBOX", _meta("2", "friend@x.com", "personal thing"))
    assert _notif(dirs, "2")["also_arrived_recently"] == []


def test_survives_a_corrupt_recent_file(dirs):
    pd.RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.RECENT_PATH.write_text("{not json")
    pd.write_notification("personal", "INBOX", _meta("1", "a@x.com", "hello"))
    assert _notifs(dirs)[0]["also_arrived_recently"] == []


def test_minutes_ago_is_reported(dirs, monkeypatch):
    pd.write_notification("personal", "INBOX", _meta("1", "a@x.com", "first"))
    real_time = time.time
    monkeypatch.setattr(pd.time, "time", lambda: real_time() + 180)
    pd.write_notification("personal", "INBOX", _meta("2", "b@x.com", "second"))
    assert _notifs(dirs)[1]["also_arrived_recently"][0]["minutes_ago"] == 3
