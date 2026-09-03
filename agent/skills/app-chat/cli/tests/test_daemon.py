"""Tests for the app-chat daemon lifecycle: defaults, the SIGTERM/daemon_died contract, and the
start/stop/restart/status verbs against the pid and port records."""

import argparse
import asyncio
import functools
import io
import json
import os
import signal
import threading
import types

import pytest
from app_chat_cli import attachments, commands, daemon
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
    # The record is "<pid> <starttime>": the pid is its first field, and whether the second one is
    # there at all depends on the fake pid happening to exist on this machine.
    assert daemon.PIDFILE.read_text().split()[0] == "4321"
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
    service = ServiceState(Store(store_path(tmp_path)), tmp_path / "notifications", tmp_path / "attachments")
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


def test_send_is_refused_while_the_user_is_talking(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    state = _daemon_state(tmp_path)
    speaking_conn: asyncio.Queue[StoredEvent] = asyncio.Queue()
    state.service.speaking.add(speaking_conn)

    refused = asyncio.run(_socket_command(state, {"command": "send", "message": "mid-turn reply"}))

    assert refused == {
        "error": "the user is talking right now: drop this reply, wait for their next message, then answer the whole thought",
        "user_speaking": True,
    }
    assert state.service.store.page()[0] == []

    state.service.speaking.discard(speaking_conn)
    accepted = asyncio.run(_socket_command(state, {"command": "send", "message": "after the turn"}))

    assert accepted == {"ok": True, "message": "after the turn", "id": 1}
    state.service.store.close()


def test_refused_send_rewakes_the_agent_when_the_floor_clears(tmp_path, monkeypatch):
    # The refusal promises a follow-up notification, and a turn can end without producing one
    # (an empty transcript), so the floor clearing after a refusal must write it itself.
    monkeypatch.delenv("AGENT_NAME", raising=False)
    state = _daemon_state(tmp_path)
    speaking_conn: asyncio.Queue[StoredEvent] = asyncio.Queue()
    state.service.set_speaking(speaking_conn, True)

    asyncio.run(_socket_command(state, {"command": "send", "message": "mid-turn reply"}))
    state.service.set_speaking(speaking_conn, False)

    files = list((tmp_path / "notifications").glob("*-app-chat-user_finished_talking.json"))
    assert len(files) == 1
    fields = json.loads(files[0].read_text())
    assert fields["source"] == "app-chat" and fields["type"] == "user_finished_talking" and fields["interrupt"] is True

    # A turn with no refusal clears silently: the marker was consumed by the one nudge above.
    state.service.set_speaking(speaking_conn, True)
    state.service.set_speaking(speaking_conn, False)
    assert len(list((tmp_path / "notifications").glob("*-app-chat-user_finished_talking.json"))) == 1
    state.service.store.close()


def test_send_acks_the_client_before_the_user_notification_finishes(tmp_path, monkeypatch):
    # The user notification can block up to its timeout. The durable ack must reach the client
    # first, so a blocking notification must not stall the send response. A read that waited on
    # the notification (the pre-ack order) would time out here instead of returning the ack.
    state = _daemon_state(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def blocking_notification(text: str) -> None:
        started.set()
        release.wait(timeout=5.0)

    monkeypatch.setattr(daemon, "_send_user_notification", blocking_notification)

    async def run() -> dict[str, object]:
        server = await asyncio.start_unix_server(functools.partial(daemon._handle_socket_conn, state), path=str(state.sock_path))
        async with server:
            reader, writer = await asyncio.open_unix_connection(str(state.sock_path))
            writer.write(json.dumps({"command": "send", "message": "hey there"}).encode())
            writer.write_eof()
            data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
            release.set()  # ack received; let the notification thread finish so shutdown is clean
            writer.close()
            await writer.wait_closed()
            return json.loads(data.decode())

    response = asyncio.run(run())

    assert response == {"ok": True, "message": "hey there", "id": 1}
    assert started.is_set()  # the notification still runs, just after the ack
    events, _ = state.service.store.page()
    assert [(e["type"], e["text"]) for e in events] == [("chat", "hey there")]
    state.service.store.close()


def test_send_notifies_even_when_the_ack_write_fails(tmp_path, monkeypatch):
    # A durable reply must still toast/push even if the caller vanished before reading the ack,
    # so a broken pipe on the ack write must not skip the notification.
    state = _daemon_state(tmp_path)
    fired = threading.Event()
    monkeypatch.setattr(daemon, "_send_user_notification", lambda text: fired.set())

    async def failing_drain(self) -> None:
        raise BrokenPipeError("client gone before reading the ack")

    monkeypatch.setattr(asyncio.StreamWriter, "drain", failing_drain)

    async def run() -> bool:
        server = await asyncio.start_unix_server(functools.partial(daemon._handle_socket_conn, state), path=str(state.sock_path))
        async with server:
            _, writer = await asyncio.open_unix_connection(str(state.sock_path))
            writer.write(json.dumps({"command": "send", "message": "hey"}).encode())
            writer.write_eof()
            fired_ok = await asyncio.to_thread(fired.wait, 5.0)
            writer.close()
            return fired_ok

    assert asyncio.run(run()) is True
    events, _ = state.service.store.page()
    assert [(e["type"], e["text"]) for e in events] == [("chat", "hey")]
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


# --- send --attach ---


def test_send_with_attach_ingests_and_carries_metadata(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    state = _daemon_state(tmp_path)
    source = tmp_path / "chart.png"
    source.write_bytes(b"pngbytes")

    response = asyncio.run(_socket_command(state, {"command": "send", "message": "here you go", "attach": [str(source)]}))

    assert response["ok"] is True and response["id"] == 1
    events, _ = state.service.store.page()
    stored = events[0]["attachments"]
    assert stored[0]["name"] == "chart.png"
    assert stored[0]["mime"] == "image/png"
    assert stored[0]["size"] == len(b"pngbytes")
    assert attachments.blob_path(tmp_path / "attachments", stored[0]["id"]).read_bytes() == b"pngbytes"
    source.unlink()  # the ingested copy stands alone
    assert attachments.blob_path(tmp_path / "attachments", stored[0]["id"]).exists()
    state.service.store.close()


def test_send_with_missing_attach_path_errors_and_persists_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    state = _daemon_state(tmp_path)

    response = asyncio.run(_socket_command(state, {"command": "send", "message": "hi", "attach": [str(tmp_path / "absent.bin")]}))

    assert "error" in response
    assert state.service.store.page()[0] == []
    state.service.store.close()


def test_send_attach_only_is_valid_and_notifies_with_the_filename(tmp_path, monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(daemon, "_send_user_notification", captured.append)
    state = _daemon_state(tmp_path)
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF")

    async def scenario() -> dict[str, object]:
        server = await asyncio.start_unix_server(functools.partial(daemon._handle_socket_conn, state), path=str(state.sock_path))
        async with server:
            reader, writer = await asyncio.open_unix_connection(str(state.sock_path))
            writer.write(json.dumps({"command": "send", "message": "", "attach": [str(source)]}).encode())
            writer.write_eof()
            data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
            writer.close()
            await writer.wait_closed()
            for _ in range(500):
                if captured:
                    break
                await asyncio.sleep(0.005)
            return json.loads(data.decode())

    response = asyncio.run(scenario())

    assert response["ok"] is True
    assert captured == ["report.pdf"]
    events, _ = state.service.store.page()
    assert events[0]["text"] == ""
    assert events[0]["attachments"][0]["name"] == "report.pdf"
    state.service.store.close()


def _send_args(tmp_path, **overrides):
    sock = tmp_path / "app-chat.sock"
    sock.touch()
    defaults = {"message": None, "socket": str(sock), "longform": False, "attach": [], "gap": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _capture_socket_request(monkeypatch):
    sent: list[tuple[str, list[str]]] = []

    async def fake_send(sock_path, message, attach):
        sent.append((message, attach))
        return {"ok": True, "message": message, "id": 1}

    monkeypatch.setattr(commands, "_send_via_socket", fake_send)
    return sent


def test_cmd_send_attach_only_skips_the_bubble_lint(tmp_path, monkeypatch, capsys):
    sent = _capture_socket_request(monkeypatch)

    commands.cmd_send(_send_args(tmp_path, attach=["/tmp/chart.png"]))

    assert sent == [("", ["/tmp/chart.png"])]
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_cmd_send_still_lints_text_when_attaching(tmp_path, monkeypatch, capsys):
    _capture_socket_request(monkeypatch)
    wall = "x" * 300

    with pytest.raises(SystemExit):
        commands.cmd_send(_send_args(tmp_path, message=[wall], attach=["/tmp/chart.png"]))
    assert "error" in json.loads(capsys.readouterr().err)


def test_cmd_send_requires_text_or_attach(tmp_path, monkeypatch, capsys):
    _capture_socket_request(monkeypatch)

    with pytest.raises(SystemExit):
        commands.cmd_send(_send_args(tmp_path))
    assert "error" in json.loads(capsys.readouterr().err)


def test_cmd_send_paces_bubbles_in_order_and_honors_the_gap(tmp_path, monkeypatch, capsys):
    sent: list[str] = []

    async def fake_send(sock_path, message, attach):
        sent.append(message)
        return {"ok": True, "message": message, "id": len(sent)}

    monkeypatch.setattr(commands, "_send_via_socket", fake_send)
    gaps: list[float] = []

    async def fake_sleep(secs):
        gaps.append(secs)

    monkeypatch.setattr(commands.asyncio, "sleep", fake_sleep)

    commands.cmd_send(_send_args(tmp_path, message=["one", "two", "three"]))

    assert sent == ["one", "two", "three"]
    # a beat between each bubble, none after the last
    assert gaps == [commands._DEFAULT_GAP_SECS, commands._DEFAULT_GAP_SECS]
    out = json.loads(capsys.readouterr().out)
    assert out["stopped_for_user"] is False
    assert [bubble["message"] for bubble in out["sent"]] == ["one", "two", "three"]


@pytest.mark.parametrize(
    ("longform", "bubbles"),
    [
        (False, ["can't wait", "see you at 8"]),
        (True, ["can't wait\n\nsee you at 8"]),
    ],
)
def test_cmd_send_reads_a_stdin_reply_as_one_bubble_per_paragraph(tmp_path, monkeypatch, capsys, longform, bubbles):
    sent = _capture_socket_request(monkeypatch)
    monkeypatch.setattr(commands.sys, "stdin", io.StringIO("can't wait\n\nsee you at 8\n"))

    commands.cmd_send(_send_args(tmp_path, message=["-"], gap=0, longform=longform))

    assert [message for message, _ in sent] == bubbles
    assert [bubble["message"] for bubble in json.loads(capsys.readouterr().out)["sent"]] == bubbles


def test_cmd_send_stops_the_waterfall_when_the_user_starts_talking(tmp_path, monkeypatch, capsys):
    sent: list[str] = []

    async def fake_send(sock_path, message, attach):
        sent.append(message)
        if message == "two":
            return {"error": "the user is talking right now: ...", "user_speaking": True}
        return {"ok": True, "message": message, "id": len(sent)}

    monkeypatch.setattr(commands, "_send_via_socket", fake_send)

    commands.cmd_send(_send_args(tmp_path, message=["one", "two", "three"], gap=0))

    assert sent == ["one", "two"]  # the refusal on "two" drops "three" before it is attempted
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": True, "sent": [{"id": 1, "message": "one"}], "stopped_for_user": True}


def test_cmd_send_pre_lints_every_bubble_and_sends_nothing_on_a_wall(tmp_path, monkeypatch, capsys):
    sent = _capture_socket_request(monkeypatch)
    wall = "x" * 300

    with pytest.raises(SystemExit):
        commands.cmd_send(_send_args(tmp_path, message=["a quick one", wall]))
    assert sent == []  # a malformed bubble stops the whole reply before anything is sent
    assert "error" in json.loads(capsys.readouterr().err)


def test_send_attach_count_is_capped(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    state = _daemon_state(tmp_path)
    source = tmp_path / "one.txt"
    source.write_bytes(b"x")

    response = asyncio.run(_socket_command(state, {"command": "send", "message": "", "attach": [str(source)] * 11}))

    assert "error" in response
    assert state.service.store.page()[0] == []
    state.service.store.close()


def test_send_attach_directory_errors_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    state = _daemon_state(tmp_path)
    directory = tmp_path / "shots"
    directory.mkdir()

    response = asyncio.run(_socket_command(state, {"command": "send", "message": "here", "attach": [str(directory)]}))

    assert "error" in response and "no such file" in str(response["error"])
    assert state.service.store.page()[0] == []
    state.service.store.close()


def test_send_attach_must_be_a_list_of_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_NAME", raising=False)
    state = _daemon_state(tmp_path)

    response = asyncio.run(_socket_command(state, {"command": "send", "message": "hi", "attach": "/tmp/x"}))

    assert response == {"error": "attach must be a list of paths"}
    state.service.store.close()


def test_run_sweep_uses_structured_references(tmp_path, monkeypatch):
    state = _daemon_state(tmp_path)
    root = state.service.attachments_root
    referenced = attachments.ingest_file(root, _seed_file(tmp_path, "keep.bin"), None)
    orphan = attachments.ingest_file(root, _seed_file(tmp_path, "orphan.bin"), None)
    state.service.store.append({"type": "chat", "ts": "2026-01-01T00:00:00", "text": "", "attachments": [referenced]})
    ancient = 1000
    for directory in (root / referenced["id"], root / orphan["id"]):
        for child in directory.iterdir():
            os.utime(child, (ancient, ancient))
        os.utime(directory, (ancient, ancient))

    swept = daemon._run_sweep(state.service)

    assert swept == 1
    assert attachments.read_meta(root, referenced["id"]) is not None
    assert attachments.read_meta(root, orphan["id"]) is None
    state.service.store.close()


def _seed_file(tmp_path, name):
    source = tmp_path / name
    source.write_bytes(b"data")
    return source
