"""EMAIL_DRAFT_ONLY hard send-disable guard in smtp_send.main().

The guard sits in main() before send() runs, so send / reply / forward invocations
are refused before any SMTP contact. Drafting (--draft) stays allowed.

smtp_send imports imap_client (which needs imap_tools/msal from the on-box runtime).
We stub those modules so the guard can be exercised without the runtime venv.
"""

import pathlib
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _install_stubs():
    """Register minimal fake imap_tools / imap_client so smtp_send imports."""
    if "imap_tools" not in sys.modules:
        it = types.ModuleType("imap_tools")

        def AND(*a, **k):  # noqa: N802 - mirrors imap_tools API name
            return None

        class MailMessageFlags:
            DRAFT = "\\Draft"
            SEEN = "\\Seen"
            ANSWERED = "\\Answered"

        it.AND = AND
        it.MailMessageFlags = MailMessageFlags
        sys.modules["imap_tools"] = it

    if "imap_client" not in sys.modules:
        ic = types.ModuleType("imap_client")
        for name in (
            "_env",
            "_from_full",
            "_to_full",
            "account_profile",
            "account_user",
            "connect",
            "get_access_token",
            "get_app_password",
            "resolve_account",
            "resolve_special_folder",
        ):
            setattr(ic, name, lambda *a, **k: None)
        sys.modules["imap_client"] = ic


_install_stubs()
import smtp_send


def _run(monkeypatch, argv, env):
    """Run smtp_send.main() with a patched send() recorder and given argv/env."""
    calls = []
    monkeypatch.setattr(smtp_send, "send", lambda *a, **k: calls.append((a, k)))
    if env is None:
        monkeypatch.delenv("EMAIL_DRAFT_ONLY", raising=False)
    else:
        monkeypatch.setenv("EMAIL_DRAFT_ONLY", env)
    monkeypatch.setattr(sys, "argv", ["email-client-send", *argv])
    return calls


SEND = ["--to", "bob@x.com", "--subject", "Hi", "--body", "hello"]
REPLY = ["--reply-to-uid", "42", "--body", "thanks"]
FORWARD = ["--forward-uid", "42", "--to", "bob@x.com", "--body", "fyi"]


def test_helper_truthy_values(monkeypatch):
    for v in ("1", "true", "TRUE", "Yes", "  yes  "):
        monkeypatch.setenv("EMAIL_DRAFT_ONLY", v)
        assert smtp_send._draft_only_enabled() is True
    for v in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("EMAIL_DRAFT_ONLY", v)
        assert smtp_send._draft_only_enabled() is False
    monkeypatch.delenv("EMAIL_DRAFT_ONLY", raising=False)
    assert smtp_send._draft_only_enabled() is False


@pytest.mark.parametrize("argv", [SEND, REPLY, FORWARD], ids=["send", "reply", "forward"])
def test_transmit_refused_in_draft_only(monkeypatch, argv):
    calls = _run(monkeypatch, argv, env="1")
    with pytest.raises(SystemExit) as ei:
        smtp_send.main()
    # Non-zero exit with a message that mentions draft-only, and send() never ran.
    assert "draft-only" in str(ei.value)
    assert calls == []


def test_draft_still_works_in_draft_only(monkeypatch):
    calls = _run(monkeypatch, [*SEND, "--draft"], env="1")
    smtp_send.main()
    # send() was reached with draft=True.
    assert len(calls) == 1
    assert calls[0][1]["draft"] is True


def test_dry_run_preview_allowed_in_draft_only(monkeypatch):
    calls = _run(monkeypatch, [*SEND, "--dry-run"], env="1")
    smtp_send.main()
    assert len(calls) == 1
    assert calls[0][1]["dry_run"] is True


@pytest.mark.parametrize("argv", [SEND, REPLY, FORWARD], ids=["send", "reply", "forward"])
def test_send_reaches_send_when_env_unset(monkeypatch, argv):
    calls = _run(monkeypatch, argv, env=None)
    smtp_send.main()
    assert len(calls) == 1
    assert calls[0][1]["draft"] is False
