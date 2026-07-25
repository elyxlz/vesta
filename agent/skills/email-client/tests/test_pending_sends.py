"""Undo-send queue (``--hold`` on email-client-send): enqueue holds, cancel
aborts, the poll daemon dispatches after fire-at and parks failures.

smtp_send/poll_daemon import imap_client (which needs imap_tools from the
on-box runtime); minimal stubs are registered first and every account/SMTP edge
smtp_send touches is monkeypatched, so the undo-window logic runs without the
runtime venv. Dispatch is driven with explicit fire-at values, never sleeps.
"""

import base64
import json
import pathlib
import sys
import time
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _install_stubs():
    """Register minimal fake imap_tools / imap_client so smtp_send and poll_daemon import."""
    if "imap_tools" not in sys.modules:
        it = types.ModuleType("imap_tools")

        def _and(*_a, **_k):
            return None

        class MailMessageFlags:
            DRAFT = "\\Draft"
            SEEN = "\\Seen"
            ANSWERED = "\\Answered"

        # The attributes mirror the imap_tools API names.
        it.AND = _and
        it.MailBox = object
        it.MailMessageFlags = MailMessageFlags
        sys.modules["imap_tools"] = it

    # Another test file may have registered a leaner imap_client stub already;
    # fill in whatever names smtp_send/poll_daemon import that it lacks (a no-op
    # when the real module is loaded).
    ic = sys.modules["imap_client"] if "imap_client" in sys.modules else types.ModuleType("imap_client")
    for name in (
        "_env",
        "_from_full",
        "_state_dir",
        "_to_full",
        "account_dir",
        "account_profile",
        "account_user",
        "connect",
        "get_access_token",
        "get_app_password",
        "list_accounts",
        "notify_folders",
        "resolve_account",
        "resolve_special_folder",
    ):
        if name not in vars(ic):
            setattr(ic, name, lambda *a, **k: None)
    sys.modules["imap_client"] = ic


_install_stubs()
import pending_sends
import poll_daemon
import smtp_send

SEND = ["--to", "bob@x.com", "--subject", "Hi", "--body", "hello"]


def _entry(token: str, fire_at: float, **over) -> pending_sends.HeldSend:
    base = {
        "token": token,
        "fire_at": fire_at,
        "created_at": 0.0,
        "account": "personal",
        "user": "me@x.com",
        "display": "Me",
        "to": "bob@x.com",
        "subject": "Hi",
        "body": "hello",
        "body_html": None,
        "cc": [],
        "bcc": [],
        "in_reply_to": "",
        "references": "",
        "attachments": [],
        "sent_sync": False,
        "reply_to_uid": None,
        "reply_folder": "INBOX",
    }
    base.update(over)
    return pending_sends.HeldSend(**base)


# -- queue mechanics ------------------------------------------------


def test_save_and_load_round_trip_including_attachments(tmp_path):
    qdir = pending_sends.queue_dir(tmp_path)
    att = pending_sends.HeldAttachment(name="a.txt", maintype="text", subtype="plain", data_b64=base64.b64encode(b"payload").decode())
    entry = _entry("t1", 10.0, attachments=[att])
    path = pending_sends.save(qdir, entry)
    assert pending_sends.load(path) == entry


def test_list_pending_sorts_by_fire_at(tmp_path):
    qdir = pending_sends.queue_dir(tmp_path)
    pending_sends.save(qdir, _entry("later", 100.0))
    pending_sends.save(qdir, _entry("sooner", 10.0))
    assert [e.token for e in pending_sends.list_pending(qdir)] == ["sooner", "later"]


def test_claim_due_takes_only_entries_past_fire_at(tmp_path):
    qdir = pending_sends.queue_dir(tmp_path)
    pending_sends.save(qdir, _entry("due", 10.0))
    pending_sends.save(qdir, _entry("early", 100.0))

    claimed = pending_sends.claim_due(qdir, now=50.0)

    assert [(path.name, entry.token) for path, entry in claimed] == [("due.sending", "due")]
    assert [e.token for e in pending_sends.list_pending(qdir)] == ["early"]


def test_cancel_prevents_dispatch(tmp_path):
    qdir = pending_sends.queue_dir(tmp_path)
    pending_sends.save(qdir, _entry("t1", 10.0))

    assert pending_sends.cancel(qdir, "t1") is True
    assert pending_sends.claim_due(qdir, now=50.0) == []
    assert pending_sends.cancel(qdir, "t1") is False


def test_fail_parks_the_claimed_entry_with_the_error(tmp_path):
    qdir = pending_sends.queue_dir(tmp_path)
    pending_sends.save(qdir, _entry("t1", 10.0))
    [(claimed, _entry_obj)] = pending_sends.claim_due(qdir, now=50.0)

    failed = pending_sends.fail(claimed, "smtp auth failed")

    assert failed.name == "t1.failed"
    assert json.loads(failed.read_text())["error"] == "smtp auth failed"
    assert not claimed.exists()
    assert pending_sends.list_pending(qdir) == []


# -- the --hold CLI path --------------------------------------------


def _prep_hold(monkeypatch, tmp_path, *, daemon_up: bool = True):
    """Point smtp_send at a tmp state dir with a stubbed account and an exploding SMTP edge."""
    delivered = []

    def boom(*_a, **_k):
        delivered.append("smtp")
        raise AssertionError("_smtp_deliver must not run while the send is held")

    monkeypatch.setattr(smtp_send, "resolve_account", lambda a: "personal")
    monkeypatch.setattr(smtp_send, "account_user", lambda a: "me@x.com")
    monkeypatch.setattr(smtp_send, "account_profile", lambda a: ("gmail", {"smtp_host": "smtp.example", "smtp_port": 587}))
    monkeypatch.setattr(smtp_send, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(smtp_send, "_env", lambda name, default=None, *, required=False: default)
    monkeypatch.setattr(smtp_send.daemon_lifecycle, "daemon_running", lambda sd: (daemon_up, 1 if daemon_up else None))
    monkeypatch.setattr(smtp_send, "_smtp_deliver", boom)
    monkeypatch.delenv("EMAIL_DRAFT_ONLY", raising=False)
    return delivered


def test_hold_enqueues_without_sending(monkeypatch, tmp_path, capsys):
    delivered = _prep_hold(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["email-client-send", *SEND, "--hold", "30"])

    smtp_send.main()

    [entry] = pending_sends.list_pending(pending_sends.queue_dir(tmp_path))
    assert (entry.account, entry.to, entry.subject, entry.body) == ("personal", "bob@x.com", "Hi", "hello")
    assert time.time() < entry.fire_at <= time.time() + 30
    out = capsys.readouterr().out
    assert f"HELD {entry.token}" in out
    assert f"email-client pending cancel {entry.token}" in out
    assert delivered == []


def test_hold_needs_the_poll_daemon_running(monkeypatch, tmp_path):
    _prep_hold(monkeypatch, tmp_path, daemon_up=False)
    monkeypatch.setattr(sys, "argv", ["email-client-send", *SEND, "--hold", "30"])

    with pytest.raises(SystemExit, match="poll daemon"):
        smtp_send.main()
    assert pending_sends.list_pending(pending_sends.queue_dir(tmp_path)) == []


@pytest.mark.parametrize("extra", [["--draft"], ["--dry-run"]], ids=["draft", "dry-run"])
def test_hold_is_mutually_exclusive_with_draft_and_dry_run(monkeypatch, extra):
    monkeypatch.setattr(sys, "argv", ["email-client-send", *SEND, "--hold", "30", *extra])
    with pytest.raises(SystemExit, match="mutually exclusive"):
        smtp_send.main()


def test_hold_rejects_nonpositive_window(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["email-client-send", *SEND, "--hold", "0"])
    with pytest.raises(SystemExit, match="positive"):
        smtp_send.main()


# -- dispatch (poll daemon side) ------------------------------------


def test_send_held_delivers_the_stored_message(monkeypatch):
    delivered = {}

    def record(acc, profile, user, host, port, msg):
        delivered.update({"acc": acc, "user": user, "host": host, "port": port, "msg": msg})

    monkeypatch.setattr(smtp_send, "account_profile", lambda a: ("gmail", {"smtp_host": "smtp.example", "smtp_port": 587}))
    monkeypatch.setattr(smtp_send, "_smtp_deliver", record)
    att = pending_sends.HeldAttachment(name="a.txt", maintype="text", subtype="plain", data_b64=base64.b64encode(b"payload").decode())
    entry = _entry("t1", 10.0, attachments=[att], cc=["cc@x.com"])

    smtp_send.send_held(entry)

    assert (delivered["acc"], delivered["user"], delivered["host"], delivered["port"]) == ("personal", "me@x.com", "smtp.example", 587)
    msg = delivered["msg"]
    assert (msg["To"], msg["Cc"], msg["Subject"]) == ("bob@x.com", "cc@x.com", "Hi")
    [attachment] = list(msg.iter_attachments())
    assert attachment.get_filename() == "a.txt"
    assert attachment.get_payload(decode=True) == b"payload"


def test_dispatch_sends_due_entries_and_clears_them(monkeypatch, tmp_path):
    qdir = pending_sends.queue_dir(tmp_path)
    pending_sends.save(qdir, _entry("due", 10.0))
    pending_sends.save(qdir, _entry("early", time.time() + 1000))
    sent = []
    monkeypatch.setattr(smtp_send, "send_held", lambda entry: sent.append(entry.token))
    logs = []

    poll_daemon.dispatch_held(tmp_path, logs.append)

    assert sent == ["due"]
    assert [e.token for e in pending_sends.list_pending(qdir)] == ["early"]
    assert not (qdir / "due.sending").exists()


def test_failed_dispatch_parks_the_entry_and_notifies(monkeypatch, tmp_path):
    qdir = pending_sends.queue_dir(tmp_path)
    pending_sends.save(qdir, _entry("t1", 10.0))

    def explode(entry):
        sys.exit("smtp auth failed")

    monkeypatch.setattr(smtp_send, "send_held", explode)
    notif_dir = tmp_path / "notifications"
    monkeypatch.setattr(poll_daemon, "NOTIF_DIR", notif_dir)
    logs = []

    poll_daemon.dispatch_held(tmp_path, logs.append)

    assert json.loads((qdir / "t1.failed").read_text())["error"] == "smtp auth failed"
    [notif_path] = list(notif_dir.glob("*.json"))
    notif = json.loads(notif_path.read_text())
    assert (notif["source"], notif["type"], notif["interrupt"]) == ("email-client", "send_failed", True)
    assert (notif["account"], notif["token"], notif["error"]) == ("personal", "t1", "smtp auth failed")
