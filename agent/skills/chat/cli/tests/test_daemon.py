"""Tests for the chat daemon lifecycle: defaults, the SIGTERM/daemon_died contract, the
start/stop/restart/status verbs against the pid and port records, and the send path that posts through
the node and leaves the local row to the replica."""

import argparse
import asyncio
import contextlib
import functools
import io
import json
import os
import signal
import types

import pytest
from chat_cli import attachments, commands, daemon
from chat_cli.node_client import NODE_UNREACHABLE
from chat_cli.replica import ReplicaState, run_replica
from chat_cli.service import ServiceState
from chat_cli.store import Store, StoredEvent, direct_room_id, store_path

from .fake_node import FakeNode, connected_client

AGENT = "vesta"
DIRECT = direct_room_id(AGENT)


@pytest.fixture
def records(tmp_path, monkeypatch):
    """Redirects the pid and port records into a tmpdir, the way a hermetic HOME would."""
    daemons_dir = tmp_path / "daemons"
    daemons_dir.mkdir()
    monkeypatch.setattr(daemon, "DAEMONS_DIR", daemons_dir)
    monkeypatch.setattr(daemon, "PIDFILE", daemons_dir / "chat.pid")
    monkeypatch.setattr(daemon, "PORTFILE", daemons_dir / "chat.port")
    monkeypatch.setattr(daemon, "LOG", tmp_path / "logs" / "chat.log")
    return daemons_dir


def test_default_notifications_dir_defaults_to_agent_notifications(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert daemon.default_notifications_dir() == tmp_path / "agent" / "notifications"


def test_default_data_dir_defaults_to_dot_chat(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert daemon.default_data_dir() == tmp_path / ".chat"


def test_write_death_notification_writes_source_and_type(tmp_path):
    notif_dir = tmp_path / "notifications"

    daemon.write_death_notification(notif_dir)

    files = list(notif_dir.glob("*-chat-daemon_died.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["source"] == "chat"
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


def test_the_replica_stays_off_without_a_node_in_the_environment(tmp_path, monkeypatch):
    state = _daemon_state(tmp_path)
    monkeypatch.delenv("AGENT_TOKEN", raising=False)

    asyncio.run(daemon._replica_loop(state))

    assert state.replica is None
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
    service = ServiceState(Store(store_path(tmp_path), AGENT), tmp_path / "notifications", tmp_path / "attachments")
    return daemon.DaemonState(
        sock_path=tmp_path / "chat.sock",
        data_dir=tmp_path,
        notifications_dir=tmp_path / "notifications",
        port=1,
        service=service,
    )


@contextlib.asynccontextmanager
async def _node_daemon(fake, tmp_path):
    """A daemon whose replica is wired to the running fake, exactly as `_replica_loop` builds it."""
    async with connected_client(fake) as client:
        state = _daemon_state(tmp_path)
        state.replica = ReplicaState(
            store=state.service.store,
            client=client,
            attachments_root=state.service.attachments_root,
            notifications_dir=state.notifications_dir,
            agent=fake.agent,
            echo=state.service.emit,
        )
        try:
            yield state
        finally:
            state.service.store.close()


def _with_node(fake, tmp_path, scenario):
    """Run one scenario against a daemon that has a node, and answer what the scenario answered."""

    async def main():
        async with _node_daemon(fake, tmp_path) as state:
            return await scenario(state)

    return asyncio.run(main())


async def _wait_for(predicate) -> None:
    """Poll a condition to a bounded deadline: the replica persists from worker threads, so an
    assertion waits for the effect instead of sleeping a guessed amount."""
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not met before the deadline")


async def _socket_command(state: daemon.DaemonState, request: dict[str, object]) -> dict[str, object]:
    server = await asyncio.start_unix_server(functools.partial(daemon._handle_socket_conn, state), path=str(state.sock_path))
    async with server:
        reader, writer = await asyncio.open_unix_connection(str(state.sock_path))
        writer.write(json.dumps(request).encode())
        writer.write_eof()
        data = await asyncio.wait_for(reader.read(65536), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        return json.loads(data.decode())


def test_send_posts_to_the_direct_room_and_leaves_the_local_row_to_the_replica(tmp_path):
    # The send owns the node post alone. The row and the echo belong to the replica's ingest of the
    # frame that comes back, so a reply is never written twice and the unique node-id index never fires.
    fake = FakeNode()
    fake.seed_room([AGENT])

    async def scenario(state):
        response = await _socket_command(state, {"command": "send", "message": "hey there"})
        return response, state.service.store.page()[0]

    response, stored = _with_node(fake, tmp_path, scenario)

    assert response == {"ok": True, "message": "hey there", "id": 1}
    assert [(message["room"], message["text"], message["sender"]) for message in fake.messages] == [(DIRECT, "hey there", AGENT)]
    assert stored == []


def test_send_to_a_peer_opens_the_room_before_posting(tmp_path):
    fake = FakeNode()

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "got a minute?", "to": "bob"})

    response = _with_node(fake, tmp_path, scenario)

    assert response["ok"] is True
    assert [(method, path) for method, path, _ in fake.requests] == [("POST", "/rooms"), ("POST", "/rooms/dm:bob:vesta/messages")]
    assert fake.messages[0]["room"] == "dm:bob:vesta"


def test_send_into_a_named_room_posts_there(tmp_path):
    fake = FakeNode()
    room = fake.seed_room([AGENT, "bob"], name="standup")

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "morning", "room": room.id})

    assert _with_node(fake, tmp_path, scenario)["ok"] is True
    assert fake.messages[0]["room"] == room.id


def test_send_takes_one_room_at_a_time(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "hi", "room": "grp-7", "to": "bob"})

    assert "error" in _with_node(fake, tmp_path, scenario)
    assert fake.messages == []


def test_a_speaking_refusal_from_the_node_reaches_the_sender(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    fake.refuse_speaking = True

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "mid-turn reply"})

    response = _with_node(fake, tmp_path, scenario)

    assert response["user_speaking"] is True
    assert "the user is talking" in str(response["error"])


def test_a_burst_refusal_is_an_error_the_sender_does_not_read_as_the_floor(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    fake.refuse_burst = True

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "and another thing"})

    response = _with_node(fake, tmp_path, scenario)

    assert "burst guard" in str(response["error"])
    assert "user_speaking" not in response


def test_a_node_failure_is_reported_and_nothing_is_stored(tmp_path):
    fake = FakeNode()  # nothing seeded, so the direct room is a 404

    async def scenario(state):
        response = await _socket_command(state, {"command": "send", "message": "hello?"})
        return response, state.service.store.page()[0]

    response, stored = _with_node(fake, tmp_path, scenario)

    assert "error" in response and "user_speaking" not in response
    assert stored == []


def test_send_without_a_node_names_the_environment_it_needs(tmp_path):
    state = _daemon_state(tmp_path)

    response = asyncio.run(_socket_command(state, {"command": "send", "message": "hey"}))

    assert response == {"error": "the chat node is unreachable: AGENT_NAME, AGENT_TOKEN, BOX_HOST, VESTAD_PORT must be set"}
    assert response["error"] == NODE_UNREACHABLE
    state.service.store.close()


def test_the_replica_writes_the_row_the_send_did_not_and_echoes_it_to_the_old_socket(tmp_path):
    # The ownership rule end to end: the reply comes back on the node's socket, the replica persists it
    # with its node id, the old service's subscribers still see it, and no notification is written for
    # this agent's own message.
    fake = FakeNode()
    fake.seed_room([AGENT])

    async def scenario(state):
        queue: asyncio.Queue[StoredEvent] = asyncio.Queue()
        state.service.subscribers.add(queue)
        shutdown = asyncio.Event()
        task = asyncio.create_task(run_replica(state.replica, shutdown))
        try:
            await _wait_for(lambda: state.replica.connected)
            response = await _socket_command(state, {"command": "send", "message": "on my way"})
            await _wait_for(lambda: queue.qsize() == 1)
            return response, state.service.store.page()[0], queue.get_nowait()
        finally:
            shutdown.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    response, stored, fanned = _with_node(fake, tmp_path, scenario)

    assert response["id"] == 1
    assert [(event["type"], event["text"], event["node_id"]) for event in stored] == [("chat", "on my way", 1)]
    assert fanned["node_id"] == 1 and fanned["sender"] == AGENT
    assert list((tmp_path / "notifications").glob("*-chat-message.json")) == []


def test_send_is_refused_while_the_user_is_talking(tmp_path):
    # The live-voice gate answers before the node is dialed at all.
    state = _daemon_state(tmp_path)
    speaking_conn: asyncio.Queue[StoredEvent] = asyncio.Queue()
    state.service.speaking.add(speaking_conn)

    refused = asyncio.run(_socket_command(state, {"command": "send", "message": "mid-turn reply"}))

    assert refused == {
        "error": "the user is talking right now: drop this reply, wait for their next message, then answer the whole thought",
        "user_speaking": True,
    }
    assert state.service.store.page()[0] == []
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

    files = list((tmp_path / "notifications").glob("*-chat-user_finished_talking.json"))
    assert len(files) == 1
    fields = json.loads(files[0].read_text())
    assert fields["source"] == "chat" and fields["type"] == "user_finished_talking" and fields["interrupt"] is True

    # A turn with no refusal clears silently: the marker was consumed by the one nudge above.
    state.service.set_speaking(speaking_conn, True)
    state.service.set_speaking(speaking_conn, False)
    assert len(list((tmp_path / "notifications").glob("*-chat-user_finished_talking.json"))) == 1
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


def test_status_command_reports_port_clients_and_the_node(tmp_path):
    state = _daemon_state(tmp_path)
    state.service.subscribers.add(asyncio.Queue())
    state.service.subscribers.add(asyncio.Queue())

    response = asyncio.run(_socket_command(state, {"command": "status"}))

    assert response == {"ok": True, "port": 1, "clients": 2, "node_connected": False}
    state.service.store.close()


def test_status_reports_a_replica_that_holds_the_node(tmp_path):
    fake = FakeNode()

    async def scenario(state):
        state.replica.connected = True
        return await _socket_command(state, {"command": "status"})

    assert _with_node(fake, tmp_path, scenario)["node_connected"] is True


# --- send --attach ---


def test_send_with_attach_uploads_it_and_keeps_the_blob_under_the_node_id(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    source = tmp_path / "chart.png"
    source.write_bytes(b"pngbytes")

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "here you go", "attach": [str(source)]})

    response = _with_node(fake, tmp_path, scenario)

    assert response["ok"] is True
    [upload] = list(fake.attachments.values())
    assert upload.finalized and bytes(upload.data) == b"pngbytes"
    assert upload.meta["name"] == "chart.png" and upload.meta["mime"] == "image/png"
    assert ("POST", f"/rooms/{DIRECT}/messages", {"text": "here you go", "attachments": [upload.meta["id"]]}) in fake.requests
    assert [meta["id"] for meta in fake.messages[0]["attachments"]] == [upload.meta["id"]]
    root = tmp_path / "attachments"
    assert attachments.blob_path(root, upload.meta["id"]).read_bytes() == b"pngbytes"
    source.unlink()  # the local copy stands alone
    assert attachments.blob_path(root, upload.meta["id"]).exists()


def test_send_with_missing_attach_path_errors_and_posts_nothing(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "hi", "attach": [str(tmp_path / "absent.bin")]})

    assert "error" in _with_node(fake, tmp_path, scenario)
    assert fake.messages == []


def test_send_attach_only_posts_an_empty_text_carrying_the_file(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    source = tmp_path / "report.pdf"
    source.write_bytes(b"%PDF")

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "", "attach": [str(source)]})

    assert _with_node(fake, tmp_path, scenario)["ok"] is True
    assert fake.messages[0]["text"] == ""
    assert [meta["name"] for meta in fake.messages[0]["attachments"]] == ["report.pdf"]


def _send_args(tmp_path, **overrides):
    sock = tmp_path / "chat.sock"
    sock.touch()
    defaults = {"message": None, "socket": str(sock), "longform": False, "attach": [], "gap": None, "room": None, "to": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _capture_socket_request(monkeypatch):
    sent: list[tuple[str, list[str]]] = []

    async def fake_send(sock_path, message, attach, room, to):
        sent.append((message, attach))
        return {"ok": True, "message": message, "id": 1}

    monkeypatch.setattr(commands, "_send_via_socket", fake_send)
    return sent


def test_cmd_send_attach_only_skips_the_bubble_lint(tmp_path, monkeypatch, capsys):
    sent = _capture_socket_request(monkeypatch)

    commands.cmd_send(_send_args(tmp_path, attach=["/tmp/chart.png"]))

    assert sent == [("", ["/tmp/chart.png"])]
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_cmd_send_carries_the_room_it_was_told_to_answer_in(tmp_path, monkeypatch, capsys):
    addressed: list[tuple[str | None, str | None]] = []

    async def fake_send(sock_path, message, attach, room, to):
        addressed.append((room, to))
        return {"ok": True, "message": message, "id": 1}

    monkeypatch.setattr(commands, "_send_via_socket", fake_send)

    commands.cmd_send(_send_args(tmp_path, message=["morning"], room="grp-7"))
    commands.cmd_send(_send_args(tmp_path, message=["morning"], to="bob"))
    commands.cmd_send(_send_args(tmp_path, message=["morning"]))

    assert addressed == [("grp-7", None), (None, "bob"), (None, None)]
    assert capsys.readouterr().out.count("\n") == 3


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

    async def fake_send(sock_path, message, attach, room, to):
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

    async def fake_send(sock_path, message, attach, room, to):
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


def test_send_attach_count_is_capped(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    source = tmp_path / "one.txt"
    source.write_bytes(b"x")

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "", "attach": [str(source)] * 11})

    assert "error" in _with_node(fake, tmp_path, scenario)
    assert fake.attachments == {}


def test_send_attach_directory_errors_cleanly(tmp_path):
    fake = FakeNode()
    fake.seed_room([AGENT])
    directory = tmp_path / "shots"
    directory.mkdir()

    async def scenario(state):
        return await _socket_command(state, {"command": "send", "message": "here", "attach": [str(directory)]})

    response = _with_node(fake, tmp_path, scenario)

    assert "error" in response and "no such file" in str(response["error"])
    assert fake.messages == []


def test_send_attach_must_be_a_list_of_paths(tmp_path):
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
