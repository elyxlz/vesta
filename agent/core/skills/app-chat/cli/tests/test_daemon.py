"""Tests for the app-chat daemon lifecycle: defaults, the stop-marker/daemon_died
contract, and the start/stop/status subcommands."""

import argparse
import asyncio
import json

import pytest
from app_chat_cli import daemon


def test_default_notifications_dir_defaults_to_agent_notifications(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert daemon.default_notifications_dir() == tmp_path / "agent" / "notifications"


def test_default_data_dir_defaults_to_dot_app_chat(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert daemon.default_data_dir() == tmp_path / ".app-chat"


def test_write_death_notification_writes_source_and_type(tmp_path):
    notif_dir = tmp_path / "notifications"

    daemon.write_death_notification(notif_dir)

    files = list(notif_dir.glob("*-app-chat-daemon_died.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["source"] == "app-chat"
    assert data["type"] == "daemon_died"


def test_intentional_stop_consumes_marker_without_notification(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    notif_dir = tmp_path / "notifications"
    marker = daemon._stop_marker_path(data_dir)
    marker.write_text("")

    daemon._consume_stop_marker_or_report_death(data_dir, notif_dir)

    assert not marker.exists()
    assert not notif_dir.exists()


def test_unmarked_exit_reports_death(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    notif_dir = tmp_path / "notifications"

    daemon._consume_stop_marker_or_report_death(data_dir, notif_dir)

    assert list(notif_dir.glob("*-app-chat-daemon_died.json"))


def test_socket_request_returns_error_when_nothing_listening(tmp_path):
    result = asyncio.run(daemon.socket_request(tmp_path / "missing.sock", {"command": "status"}))
    assert "error" in result


def test_socket_request_round_trips_through_a_real_unix_socket(tmp_path):
    sock_path = tmp_path / "app-chat.sock"

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(65536)
        request = json.loads(data.decode())
        writer.write(json.dumps({"ok": True, "connected": True, "ws_url": request["command"]}).encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def scenario() -> dict[str, object]:
        server = await asyncio.start_unix_server(handler, path=str(sock_path))
        async with server:
            return await daemon.socket_request(sock_path, {"command": "status"})

    result = asyncio.run(scenario())
    assert result == {"ok": True, "connected": True, "ws_url": "status"}


def test_daemon_alive_false_when_socket_missing(tmp_path):
    assert daemon.daemon_alive(tmp_path / "nope.sock") is False


def test_daemon_alive_reflects_socket_request_result(tmp_path, monkeypatch):
    sock_path = tmp_path / "app-chat.sock"
    sock_path.write_text("")

    async def fake_ok(sock_path, request, timeout=daemon.SOCKET_TIMEOUT):
        return {"ok": True, "connected": False, "ws_url": "ws://x"}

    async def fake_error(sock_path, request, timeout=daemon.SOCKET_TIMEOUT):
        return {"error": "connection refused"}

    monkeypatch.setattr(daemon, "socket_request", fake_ok)
    assert daemon.daemon_alive(sock_path) is True

    monkeypatch.setattr(daemon, "socket_request", fake_error)
    assert daemon.daemon_alive(sock_path) is False


def _args(tmp_path) -> argparse.Namespace:
    return argparse.Namespace(data_dir=str(tmp_path / "data"))


def test_daemon_start_is_idempotent_when_already_running(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(daemon, "daemon_alive", lambda sock_path: True)
    monkeypatch.setattr(daemon.subprocess, "run", lambda *a, **k: pytest.fail("should not launch a duplicate daemon"))

    daemon.cmd_daemon_start(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {"status": "already_running", "session": "app-chat"}


def test_daemon_start_errors_when_screen_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(daemon, "daemon_alive", lambda sock_path: False)
    monkeypatch.setattr(daemon.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit) as exc:
        daemon.cmd_daemon_start(_args(tmp_path))

    assert exc.value.code == 1
    assert "screen" in json.loads(capsys.readouterr().out)["error"]


def test_daemon_start_launches_and_waits_for_the_socket(tmp_path, monkeypatch, capsys):
    calls = {"alive": 0, "launched": False}

    def fake_alive(sock_path):
        calls["alive"] += 1
        return calls["launched"]

    def fake_run(cmd, check):
        calls["launched"] = True

    monkeypatch.setattr(daemon, "daemon_alive", fake_alive)
    monkeypatch.setattr(daemon.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    monkeypatch.setattr(daemon.time, "sleep", lambda seconds: None)

    daemon.cmd_daemon_start(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {"status": "started", "session": "app-chat"}
    assert calls["launched"] is True


def test_daemon_start_clears_a_leaked_stop_marker_before_launching(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    daemon._stop_marker_path(data_dir).write_text("")

    calls = {"launched": False}

    def fake_alive(sock_path):
        return calls["launched"]

    def fake_run(cmd, check):
        calls["launched"] = True
        # the leaked marker must be gone before the fresh daemon is launched, so its own
        # unexpected death still reports daemon_died rather than silently consuming the marker
        assert not daemon._stop_marker_path(data_dir).exists()

    monkeypatch.setattr(daemon, "daemon_alive", fake_alive)
    monkeypatch.setattr(daemon.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    monkeypatch.setattr(daemon.time, "sleep", lambda seconds: None)

    daemon.cmd_daemon_start(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {"status": "started", "session": "app-chat"}
    assert not daemon._stop_marker_path(data_dir).exists()


def test_daemon_stop_is_idempotent_when_already_stopped(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(daemon, "daemon_alive", lambda sock_path: False)

    daemon.cmd_daemon_stop(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {"status": "already_stopped", "session": "app-chat"}


def test_daemon_stop_writes_marker_before_quitting(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    calls = {"alive": 0}

    def fake_alive(sock_path):
        calls["alive"] += 1
        return calls["alive"] == 1  # alive on the first check, gone after the quit signal

    quit_calls = []

    def fake_run(cmd, check):
        quit_calls.append(cmd)
        # the marker must exist before the process is signaled, mirroring what serve consumes
        assert daemon._stop_marker_path(data_dir).exists()

    monkeypatch.setattr(daemon, "daemon_alive", fake_alive)
    monkeypatch.setattr(daemon.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    monkeypatch.setattr(daemon.time, "sleep", lambda seconds: None)

    daemon.cmd_daemon_stop(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {"status": "stopped", "session": "app-chat"}
    assert quit_calls == [["/usr/bin/screen", "-S", "app-chat", "-X", "quit"]]


def test_daemon_status_reports_not_running_when_socket_absent(tmp_path, capsys):
    daemon.cmd_daemon_status(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {"running": False, "session": "app-chat"}


def test_daemon_status_reports_ws_connection_state_when_running(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sock_path = daemon._sock_path(data_dir)
    sock_path.write_text("")

    async def fake_status(sock_path, request, timeout=daemon.SOCKET_TIMEOUT):
        return {"ok": True, "connected": True, "ws_url": "ws://localhost:1234/ws"}

    monkeypatch.setattr(daemon, "socket_request", fake_status)

    daemon.cmd_daemon_status(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {
        "running": True,
        "session": "app-chat",
        "ws_connected": True,
        "ws_url": "ws://localhost:1234/ws",
    }


def test_ws_loop_connects_with_unlimited_max_msg_size(monkeypatch, tmp_path):
    """Regression: the core pushes an unbounded history/state frame on connect and the daemon
    only drains+discards inbound frames, so ws_connect must set max_msg_size=0. A finite cap
    (aiohttp's 4MB default) makes the socket error on the oversized frame and reconnect forever,
    breaking the send path with 'not connected to agent'."""
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
    state = daemon.DaemonState(
        ws_url="ws://localhost/ws",
        sock_path=tmp_path / "s.sock",
        data_dir=tmp_path,
        notifications_dir=tmp_path / "notifications",
    )
    captured_kwargs: dict[str, object] = {}

    class _FakeWS:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class _FakeWSCtx:
        async def __aenter__(self):
            state.shutdown.set()  # exit the loop after this single iteration
            return _FakeWS()

        async def __aexit__(self, *_exc):
            return False

    def _fake_ws_connect(url, **kwargs):
        captured_kwargs.update(kwargs)
        return _FakeWSCtx()

    class _FakeSession:
        ws_connect = staticmethod(_fake_ws_connect)

    monkeypatch.setattr(state, "session", _FakeSession())

    asyncio.run(daemon._ws_loop(state))

    assert captured_kwargs.get("max_msg_size") == 0
