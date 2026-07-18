"""Admin lifecycle tests that don't require a live daemon."""

from __future__ import annotations

import os
import signal
import socket
import threading

from vesta_browser import admin, daemon

HANG_GUARD_S = 5


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
    assert str(admin._session_file(None, "browser-pid")) == "/tmp/vesta-browser-work.browser-pid"
    assert str(admin._session_file("other", "bidi-ws")) == "/tmp/vesta-browser-other.bidi-ws"


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
    assert admin._pid_alive(2**31 - 1) is False


def test_terminate_pid_no_op_when_already_dead():
    admin._terminate_pid(2**31 - 1)


def test_terminate_pid_stops_a_child():
    """Spawn a sleep and make sure _terminate_pid reaps it within the grace window."""
    import subprocess

    p = subprocess.Popen(["sleep", "60"])
    try:
        admin._terminate_pid(p.pid)
    finally:
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
    assert p.returncode is not None
    assert p.returncode in (-signal.SIGTERM, 0)


def test_read_session_ws_url_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("BROWSER_SESSION", "missing-" + tmp_path.name)
    assert admin.read_session_ws_url() is None


def test_read_session_ws_url_reads(tmp_path, monkeypatch):
    session = "wscheck-" + tmp_path.name
    monkeypatch.setenv("BROWSER_SESSION", session)
    admin._session_file(None, "bidi-ws").write_text("ws://127.0.0.1:5555/session\n")
    try:
        assert admin.read_session_ws_url() == "ws://127.0.0.1:5555/session"
    finally:
        admin._session_file(None, "bidi-ws").unlink()


def test_read_mode_defaults_to_a11y(monkeypatch, tmp_path):
    monkeypatch.setenv("BROWSER_SESSION", "modemissing-" + tmp_path.name)
    assert admin.read_mode() == "a11y"


def test_set_and_read_mode_roundtrip(tmp_path, monkeypatch):
    session = "modecheck-" + tmp_path.name
    monkeypatch.setenv("BROWSER_SESSION", session)
    try:
        admin.set_mode("screenshot")
        assert admin.read_mode() == "screenshot"
        admin.set_mode("both")
        assert admin.read_mode() == "both"
    finally:
        admin._session_file(None, "mode").unlink(missing_ok=True)


def test_set_mode_rejects_unknown(monkeypatch, tmp_path):
    monkeypatch.setenv("BROWSER_SESSION", "modebad-" + tmp_path.name)
    import pytest

    with pytest.raises(ValueError, match="mode must be one of"):
        admin.set_mode("hologram")


def test_read_mode_falls_back_on_garbage(tmp_path, monkeypatch):
    session = "modegarbage-" + tmp_path.name
    monkeypatch.setenv("BROWSER_SESSION", session)
    admin._session_file(None, "mode").write_text("nonsense")
    try:
        assert admin.read_mode() == "a11y"
    finally:
        admin._session_file(None, "mode").unlink(missing_ok=True)


def test_send_times_out_when_the_daemon_never_replies(tmp_path, monkeypatch):
    """A daemon that accepts the request and goes quiet must surface an error, not hang."""
    monkeypatch.setattr(admin, "DAEMON_RESPONSE_TIMEOUT_S", 0.3)
    sock_path = str(tmp_path / "silent.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(sock_path)
    listener.listen(1)
    monkeypatch.setattr(admin, "socket_path", lambda name=None: sock_path)

    raised: list[BaseException] = []

    def call_send() -> None:
        try:
            admin.send({"method": "browsingContext.create", "params": {"type": "tab"}})
        except BaseException as e:
            raised.append(e)

    caller = threading.Thread(target=call_send, daemon=True)
    caller.start()
    try:
        caller.join(timeout=HANG_GUARD_S)
        assert not caller.is_alive(), "admin.send() hung: the daemon socket read is unbounded"
        assert isinstance(raised[0], RuntimeError)
        assert "did not respond to 'browsingContext.create' within 0.3s" in str(raised[0])
    finally:
        listener.close()
