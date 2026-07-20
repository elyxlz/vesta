"""Tests for the app-chat daemon lifecycle: defaults, the stop-marker/daemon_died
contract, and the start/stop/status subcommands."""

import argparse
import asyncio
import functools
import json

import pytest
from app_chat_cli import daemon
from app_chat_cli.service import ServiceState
from app_chat_cli.store import Store, StoredEvent, store_path


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
        writer.write(json.dumps({"ok": True, "port": 4321, "clients": 0, "echo": request["command"]}).encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def scenario() -> dict[str, object]:
        server = await asyncio.start_unix_server(handler, path=str(sock_path))
        async with server:
            return await daemon.socket_request(sock_path, {"command": "status"})

    result = asyncio.run(scenario())
    assert result == {"ok": True, "port": 4321, "clients": 0, "echo": "status"}


def test_daemon_alive_false_when_socket_missing(tmp_path):
    assert daemon.daemon_alive(tmp_path / "nope.sock") is False


def test_daemon_alive_reflects_socket_request_result(tmp_path, monkeypatch):
    sock_path = tmp_path / "app-chat.sock"
    sock_path.write_text("")

    async def fake_ok(sock_path, request, timeout=daemon.SOCKET_TIMEOUT):
        return {"ok": True, "port": 4321, "clients": 0}

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


def test_daemon_status_reports_port_and_client_count_when_running(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sock_path = daemon._sock_path(data_dir)
    sock_path.write_text("")

    async def fake_status(sock_path, request, timeout=daemon.SOCKET_TIMEOUT):
        return {"ok": True, "port": 1234, "clients": 2}

    monkeypatch.setattr(daemon, "socket_request", fake_status)

    daemon.cmd_daemon_status(_args(tmp_path))

    assert json.loads(capsys.readouterr().out) == {
        "running": True,
        "session": "app-chat",
        "port": 1234,
        "clients": 2,
    }


def _daemon_state(tmp_path) -> daemon.DaemonState:
    service = ServiceState(Store(store_path(tmp_path)), tmp_path / "notifications")
    return daemon.DaemonState(
        sock_path=tmp_path / "app-chat.sock",
        data_dir=tmp_path,
        notifications_dir=tmp_path / "notifications",
        port=1,
        service=service,
    )


async def _socket_command(state: daemon.DaemonState, request: dict[str, str]) -> dict[str, object]:
    server = await asyncio.start_unix_server(functools.partial(daemon._handle_socket_conn, state), path=str(state.sock_path))
    async with server:
        reader, writer = await asyncio.open_unix_connection(str(state.sock_path))
        writer.write(json.dumps(request).encode())
        writer.write_eof()
        data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        return json.loads(data.decode())


def test_send_command_persists_chat_event_and_fans_it_to_subscribers(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    state = _daemon_state(tmp_path)
    queue: asyncio.Queue[StoredEvent] = asyncio.Queue()
    state.service.subscribers.add(queue)

    response = asyncio.run(_socket_command(state, {"command": "send", "message": "hey there"}))

    assert response == {"ok": True, "message": "hey there", "id": 1}
    events, _ = state.service.store.page()
    assert [(e["type"], e["text"]) for e in events] == [("chat", "hey there")]
    assert queue.qsize() == 1
    fanned = queue.get_nowait()
    assert fanned["id"] == 1 and fanned["type"] == "chat"
    state.service.store.close()


def test_send_command_rejects_empty_message(tmp_path):
    state = _daemon_state(tmp_path)
    queue: asyncio.Queue[StoredEvent] = asyncio.Queue()
    state.service.subscribers.add(queue)

    response = asyncio.run(_socket_command(state, {"command": "send", "message": "   "}))

    assert response == {"error": "empty message"}
    assert state.service.store.page()[0] == []
    assert queue.qsize() == 0
    state.service.store.close()


def test_status_command_reports_port_and_connected_client_count(tmp_path):
    state = _daemon_state(tmp_path)
    state.service.subscribers.add(asyncio.Queue())
    state.service.subscribers.add(asyncio.Queue())

    response = asyncio.run(_socket_command(state, {"command": "status"}))

    assert response == {"ok": True, "port": 1, "clients": 2}
    state.service.store.close()


def test_send_user_notification_shells_the_script_with_kind_agent_and_preview(tmp_path, monkeypatch):
    script = tmp_path / "user-notification"
    script.write_text("#!/usr/bin/env bash\ntrue\n")
    monkeypatch.setattr(daemon, "USER_NOTIFICATION", script)
    monkeypatch.setenv("AGENT_NAME", "aria")
    calls = []
    monkeypatch.setattr(daemon.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))

    daemon._send_user_notification("a long reply " * 40)

    assert len(calls) == 1
    argv = calls[0]
    assert argv[:3] == [str(script), "message", "aria"]
    assert len(argv[3]) == 180  # the body preview is truncated


def test_send_user_notification_swallows_a_spawn_error(tmp_path, monkeypatch):
    script = tmp_path / "user-notification"
    script.write_text("#!/usr/bin/env bash\ntrue\n")
    monkeypatch.setattr(daemon, "USER_NOTIFICATION", script)
    monkeypatch.setenv("AGENT_NAME", "aria")

    def raising_run(cmd, **kwargs):
        raise OSError("exec format error")

    monkeypatch.setattr(daemon.subprocess, "run", raising_run)

    # a spawn failure must never propagate: persist + emit already happened, so the send response
    # must still be written
    daemon._send_user_notification("hello")


def test_send_user_notification_swallows_a_timeout(tmp_path, monkeypatch):
    script = tmp_path / "user-notification"
    script.write_text("#!/usr/bin/env bash\ntrue\n")
    monkeypatch.setattr(daemon, "USER_NOTIFICATION", script)
    monkeypatch.setenv("AGENT_NAME", "aria")

    def timing_out_run(cmd, **kwargs):
        raise daemon.subprocess.TimeoutExpired(cmd, daemon.USER_NOTIFICATION_TIMEOUT)

    monkeypatch.setattr(daemon.subprocess, "run", timing_out_run)

    daemon._send_user_notification("hello")


def test_send_user_notification_is_a_noop_when_agent_name_or_script_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon.subprocess, "run", lambda *a, **k: pytest.fail("must not shell when a guard fails"))

    # script missing, AGENT_NAME set
    monkeypatch.setattr(daemon, "USER_NOTIFICATION", tmp_path / "missing-user-notification")
    monkeypatch.setenv("AGENT_NAME", "aria")
    daemon._send_user_notification("hello")

    # script present, AGENT_NAME unset
    script = tmp_path / "user-notification"
    script.write_text("#!/usr/bin/env bash\ntrue\n")
    monkeypatch.setattr(daemon, "USER_NOTIFICATION", script)
    monkeypatch.delenv("AGENT_NAME", raising=False)
    daemon._send_user_notification("hello")
