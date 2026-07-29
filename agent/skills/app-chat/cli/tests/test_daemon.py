"""Tests for the app-chat daemon lifecycle: defaults, the SIGTERM/daemon_died contract, and the
start/stop/restart/status verbs against the pid and port records."""

import asyncio
import functools
import json
import os
import signal
import types

import pytest
from app_chat_cli import daemon
from app_chat_cli.service import ServiceState
from app_chat_cli.store import Store, StoredEvent, store_path


@pytest.fixture
def records(tmp_path, monkeypatch):
    """Redirects the pid and port records into a tmpdir, the way a hermetic HOME would."""
    daemons_dir = tmp_path / "daemons"
    daemons_dir.mkdir()
    monkeypatch.setattr(daemon, "DAEMONS_DIR", daemons_dir)
    monkeypatch.setattr(daemon, "PIDFILE", daemons_dir / "app-chat.pid")
    monkeypatch.setattr(daemon, "PORTFILE", daemons_dir / "app-chat.port")
    monkeypatch.setattr(daemon, "LOG", tmp_path / "logs" / "app-chat.log")
    return daemons_dir


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


def test_a_sigterm_is_the_one_shutdown_that_stays_quiet(tmp_path):
    state = _daemon_state(tmp_path)

    daemon._begin_shutdown(state, signal.SIGTERM)

    assert state.asked_to_stop is True
    assert state.shutdown.is_set()
    state.service.store.close()


def test_any_other_signal_leaves_the_death_report_armed(tmp_path):
    state = _daemon_state(tmp_path)

    daemon._begin_shutdown(state, signal.SIGINT)

    assert state.asked_to_stop is False
    assert state.shutdown.is_set()
    state.service.store.close()


def test_live_pid_is_none_without_a_record(records):
    assert daemon.live_pid() is None


def test_live_pid_is_none_for_a_pid_nobody_is_running(records):
    daemon.PIDFILE.write_text("2147483646")
    assert daemon.live_pid() is None


def test_live_pid_reads_back_a_running_process(records):
    daemon.PIDFILE.write_text(str(os.getpid()))
    assert daemon.live_pid() == os.getpid()


def test_start_is_a_no_op_while_the_recorded_process_is_alive(records, monkeypatch, capsys):
    daemon.PIDFILE.write_text(str(os.getpid()))
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("should not launch a duplicate daemon"))

    assert daemon.daemon_cmd("start") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already_running"}


def test_start_fails_closed_when_registration_fails(records, monkeypatch, capsys):
    monkeypatch.setattr(daemon, "_register_port", lambda: None)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch without a port"))

    assert daemon.daemon_cmd("start") == 1
    assert "register" in json.loads(capsys.readouterr().err)["error"]
    assert not daemon.PIDFILE.exists()


def test_start_records_the_pid_and_port_of_a_daemon_that_answers(records, monkeypatch, capsys):
    launched = []

    def fake_popen(argv, **kwargs):
        launched.append(argv)
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(daemon, "_register_port", lambda: "5150")
    monkeypatch.setattr(daemon, "_ready", lambda port: True)
    monkeypatch.setattr(daemon.subprocess, "Popen", fake_popen)

    assert daemon.daemon_cmd("start") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "started"}
    assert launched[0][1:] == ["serve", "--port", "5150"]
    assert daemon.PIDFILE.read_text() == "4321"
    assert daemon.PORTFILE.read_text() == "5150"


def test_stop_is_idempotent_when_nothing_is_recorded(records, capsys):
    assert daemon.daemon_cmd("stop") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already_stopped"}


def test_stop_sends_a_sigterm_and_clears_both_records(records, monkeypatch, capsys):
    daemon.PIDFILE.write_text("4321")
    daemon.PORTFILE.write_text("5150")
    signals = []
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    # alive for the signal, gone on the first poll after it
    monkeypatch.setattr(daemon, "live_pid", iter([4321, None]).__next__)

    assert daemon.daemon_cmd("stop") == 0
    assert signals == [(4321, signal.SIGTERM)]
    assert json.loads(capsys.readouterr().out) == {"status": "stopped"}
    assert not daemon.PIDFILE.exists()
    assert not daemon.PORTFILE.exists()


def test_restart_prints_one_line_and_skips_the_start_when_the_stop_fails(records, monkeypatch, capsys):
    daemon.PIDFILE.write_text(str(os.getpid()))
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(daemon, "STOP_TIMEOUT_SECS", 0)
    monkeypatch.setattr(daemon, "_start", lambda: pytest.fail("must not start onto a daemon that is still there"))

    assert daemon.daemon_cmd("restart") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SIGTERM" in json.loads(captured.err)["error"]


def test_status_reports_not_running_without_a_record(records, capsys):
    assert daemon.daemon_cmd("status") == 0
    assert json.loads(capsys.readouterr().out) == {"running": False, "port": None}


def test_status_reads_the_port_start_recorded(records, capsys):
    daemon.PIDFILE.write_text(str(os.getpid()))
    daemon.PORTFILE.write_text("5150")

    assert daemon.daemon_cmd("status") == 0
    assert json.loads(capsys.readouterr().out) == {"running": True, "port": 5150}


def test_the_help_forms_succeed_and_an_unknown_verb_does_not(records, capsys):
    for action in ("", "-h", "--help", "help"):
        assert daemon.daemon_cmd(action) == 0
    assert "Usage" in capsys.readouterr().out
    assert daemon.daemon_cmd("bogus") == 1
    assert "Usage" in capsys.readouterr().err


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
