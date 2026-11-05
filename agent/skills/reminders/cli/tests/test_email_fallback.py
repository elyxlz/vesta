"""Tests for the daemon-side email fallback (_email_fallback, 5/11/2026).

Born from a 12-day drift: MEMORY says every reminder gets an email copy at
emanuele@, but the copy was an agent-memory duty and silently stopped on
24/10/2026 (last "Promemoria HH:MM" email). The fallback now lives in the
daemon right after write_reminder_notification, where it cannot be forgotten.

All tests are hermetic: subprocess.run is monkeypatched, no SMTP is touched.
"""
import subprocess

import pytest

from reminders_cli.commands import _email_fallback


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("REMINDER_FALLBACK_OFF", raising=False)
    monkeypatch.delenv("REMINDER_FALLBACK_TO", raising=False)
    monkeypatch.delenv("REMINDER_FALLBACK_ACCOUNT", raising=False)


def test_off_flag_skips_send(monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    monkeypatch.setenv("REMINDER_FALLBACK_OFF", "1")
    _email_fallback("abc123", "call mom")
    assert called == []


def test_sends_email_client_send_with_defaults(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    _email_fallback("abc123", "call mom")
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[:2] == ["email-client-send", "--account"]
    assert "emanuele@alphalabs.it" in cmd
    joined = " ".join(cmd)
    assert "Promemoria: call mom" in joined
    assert "--no-sent-sync" not in joined


def test_env_overrides(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    monkeypatch.setenv("REMINDER_FALLBACK_TO", "other@example.com")
    monkeypatch.setenv("REMINDER_FALLBACK_ACCOUNT", "personal")
    _email_fallback("abc123", "call mom")
    cmd = calls[0]
    assert "other@example.com" in cmd
    assert "personal" in cmd


def test_nonzero_rc_does_not_raise(monkeypatch):
    def fail(cmd, **k):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="smtp down")

    monkeypatch.setattr(subprocess, "run", fail)
    _email_fallback("abc123", "call mom")  # must not raise


def test_subprocess_exception_does_not_raise(monkeypatch):
    def boom(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 90)

    monkeypatch.setattr(subprocess, "run", boom)
    _email_fallback("abc123", "call mom")  # must not raise
