"""Admin lifecycle tests that don't require a live daemon."""

from __future__ import annotations

import os
import signal

from vesta_browser import admin, daemon


def test_session_name_default(monkeypatch):
    monkeypatch.delenv("BROWSER_SESSION", raising=False)
    assert admin._session_name() == "default"


def test_session_name_from_env(monkeypatch):
    monkeypatch.setenv("BROWSER_SESSION", "agent-7")
    assert admin._session_name() == "agent-7"


def test_session_name_override():
    assert admin._session_name("explicit") == "explicit"


def test_socket_path_format(monkeypatch):
    monkeypatch.setenv("BROWSER_SESSION", "scrape")
    assert daemon.socket_path() == "/tmp/vesta-browser-scrape.sock"


def test_session_file_includes_session_and_suffix(monkeypatch):
    monkeypatch.setenv("BROWSER_SESSION", "work")
    assert str(admin._session_file(None, "chrome-pid")) == "/tmp/vesta-browser-work.chrome-pid"
    assert str(admin._session_file("other", "cdp-port")) == "/tmp/vesta-browser-other.cdp-port"


def test_daemon_alive_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_SESSION", "nobody-home-" + str(tmp_path).replace("/", "_"))
    assert admin.daemon_alive() is False


def test_list_sessions_returns_list():
    out = admin.list_sessions()
    assert isinstance(out, list)


def test_read_pid_returns_none_for_missing(tmp_path):
    assert admin._read_pid(tmp_path / "nope") is None


def test_read_pid_returns_none_for_garbage(tmp_path):
    p = tmp_path / "pid"
    p.write_text("not-a-number\n")
    assert admin._read_pid(p) is None


def test_read_pid_parses_int(tmp_path):
    p = tmp_path / "pid"
    p.write_text("12345\n")
    assert admin._read_pid(p) == 12345


def test_pid_alive_self():
    assert admin._pid_alive(os.getpid()) is True


def test_pid_alive_false_for_reserved_pid():
    # PID 0 is reserved; os.kill(0, 0) raises PermissionError on most systems.
    # Our helper treats PermissionError as not-alive (conservative).
    # Pick an obviously-dead pid instead.
    assert admin._pid_alive(2**31 - 1) is False


def test_terminate_pid_no_op_when_already_dead():
    # Non-existent PID should not raise.
    admin._terminate_pid(2**31 - 1)


def test_terminate_pid_stops_a_child():
    """Spawn a sleep and make sure _terminate_pid reaps it within the grace window."""
    import subprocess

    p = subprocess.Popen(["sleep", "60"])
    try:
        admin._terminate_pid(p.pid)
    finally:
        # Reap the zombie if it survived somehow.
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    assert p.returncode is not None
    # SIGTERM yields -15 on posix, or 0 if child exits normally (not expected for sleep).
    assert p.returncode in (-signal.SIGTERM, 0)


def test_read_session_port_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("BROWSER_SESSION", "missing-" + tmp_path.name)
    assert admin.read_session_port() is None


def test_read_session_port_parses(tmp_path, monkeypatch):
    session = "portcheck-" + tmp_path.name
    monkeypatch.setenv("BROWSER_SESSION", session)
    admin._session_file(None, "cdp-port").write_text("9233\n")
    try:
        assert admin.read_session_port() == 9233
    finally:
        admin._session_file(None, "cdp-port").unlink()
