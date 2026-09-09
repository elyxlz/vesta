"""Chat daemon.

Owns the chat channel: it replicates every room vestad's chat node holds this agent in, and accepts
CLI commands over a Unix socket to send replies (`chat send` -> upload each attachment to the node,
post the message, answer the node's id). The local row of a reply belongs to the replica, which
persists the frame the node sends back, so a reply is written exactly once. It serves no port and
registers no service: the node holds the rooms the app reads.

`chat daemon start|stop|restart|status` owns the process lifecycle: start returns once the socket
answers `status`, stop is a SIGTERM the serve path reads as deliberate, and status answers from the
pid record alone.
"""

import argparse
import asyncio
import contextlib
import functools
import io
import json
import mimetypes
import os
import pathlib as pl
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import attachments
from .node_client import NODE_UNREACHABLE, BurstRefusedError, NodeClient, NodeError, SpeakingRefusedError, new_session, node_config_from_env
from .replica import ReplicaState, run_replica
from .store import Store, direct_room_id, store_path

NAME = "chat"
DAEMONS_DIR = pl.Path.home() / "agent/data/daemons"
PIDFILE = DAEMONS_DIR / f"{NAME}.pid"
LOG = pl.Path.home() / "agent/logs" / f"{NAME}.log"
USAGE = f"Usage: {NAME} daemon <start|stop|restart|status>"
POLL_SECS = 0.5
# How long a start that lost the record claim waits for the rival start to resolve.
CLAIM_WAIT_SECS = 3
# One hung probe must not eat the whole readiness budget.
PROBE_TIMEOUT_SECS = 2
# The readiness answer is one small JSON line; anything longer is not the daemon.
PROBE_ANSWER_BYTES = 4096


def _budget(name: str, default: int) -> int:
    return int(os.environ[name]) if name in os.environ else default


# A readiness budget is a bet about disk speed, and boot is when that bet is worst:
# every call cold, nothing in page cache, several daemons starting at once. A miss is not a retry.
# `_abandon` TERMs then KILLs a child that `child.poll()` just showed to be ALIVE, so a daemon that
# is merely slow to import is destroyed and the caller is handed an error that reads like a crash.
# This is a user-facing channel, so a boot that silently loses it is the expensive failure.
# Raising the ceiling costs a healthy start nothing: it returns the moment the socket answers,
# in about a second.
READY_TIMEOUT_SECS = _budget("DAEMON_READY_TIMEOUT_SECS", 120)
STOP_TIMEOUT_SECS = _budget("DAEMON_STOP_TIMEOUT_SECS", 15)

# Attachment GC cadence: soon after start (off the readiness path), then a few times a day. A blob
# nothing references ages out at attachments.STALE_ATTACHMENT_MAX_AGE_SECS.
SWEEP_STARTUP_DELAY_SECS = 60.0
SWEEP_INTERVAL_SECS = 6 * 3600.0


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def default_data_dir() -> pl.Path:
    return pl.Path.home() / ".chat"


def default_notifications_dir() -> pl.Path:
    return pl.Path.home() / "agent" / "notifications"


def agent_name() -> str:
    """This agent's name, which vestad writes into the container's environment. It names the direct
    room, so the store takes it and never reads the environment itself. Without it every room id would
    read `dm:`, so the command ends here with the one error line instead."""
    name = os.environ["AGENT_NAME"] if "AGENT_NAME" in os.environ else ""
    if not name:
        sys.exit(_fail("AGENT_NAME is not set"))
    return name


def _sock_path(data_dir: pl.Path) -> pl.Path:
    return data_dir / "chat.sock"


@dataclass
class DaemonState:
    sock_path: pl.Path
    notifications_dir: pl.Path
    store: Store
    attachments_root: pl.Path
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)
    asked_to_stop: bool = False
    # The node replica, from the moment the loop builds it. None while the environment names no node.
    replica: ReplicaState | None = None


def cmd_serve(args: argparse.Namespace) -> None:
    data_dir = pl.Path(args.data_dir or default_data_dir())
    data_dir.mkdir(parents=True, exist_ok=True)
    state = DaemonState(
        sock_path=_sock_path(data_dir),
        notifications_dir=default_notifications_dir(),
        store=Store(store_path(data_dir), agent_name()),
        attachments_root=attachments.attachments_root(data_dir),
    )
    asyncio.run(_run(state))


def _begin_shutdown(state: DaemonState, sig: signal.Signals) -> None:
    """SIGTERM is what `chat daemon stop` sends, so it is the one exit the agent asked for;
    every other way out is news the agent needs."""
    state.asked_to_stop = sig == signal.SIGTERM
    state.shutdown.set()


async def _run(state: DaemonState) -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, functools.partial(_begin_shutdown, state, sig))

    tasks = [asyncio.create_task(_socket_server(state)), asyncio.create_task(_sweep_loop(state)), asyncio.create_task(_replica_loop(state))]
    try:
        await state.shutdown.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        state.store.close()
        state.sock_path.unlink(missing_ok=True)
        if not state.asked_to_stop:
            write_death_notification(state.notifications_dir)


async def _replica_loop(state: DaemonState) -> None:
    """Replicate every room the node holds this agent in, for as long as the daemon runs. With no node
    identity in the environment the loop says so once and stays off, and the rest of the daemon works
    as it does with a node."""
    config = node_config_from_env(os.environ)
    if config is None:
        _log("no node identity in the environment (AGENT_NAME, AGENT_TOKEN, BOX_HOST, VESTAD_PORT): not replicating")
        return
    session = new_session(config)
    try:
        state.replica = ReplicaState(
            store=state.store,
            client=NodeClient(config, session),
            attachments_root=state.attachments_root,
            notifications_dir=state.notifications_dir,
            agent=config["agent"],
        )
        await run_replica(state.replica, state.shutdown)
    finally:
        # Shielded, because this cleanup runs on the cancellation that stops the daemon: the session
        # must close whether or not the task is cancelled again while it does.
        await asyncio.shield(session.close())


def _run_sweep(state: DaemonState) -> int:
    """One GC pass: attachment directories no message references, older than the max age. Referenced
    ids come from one structured scan of the store."""
    references = state.store.attachment_references()
    swept = attachments.sweep(state.attachments_root, time.time(), lambda attachment_id: attachment_id in references)
    return len(swept)


async def _sweep_loop(state: DaemonState) -> None:
    """Periodic GC, first pass shortly after start (never before the socket answers: a large history
    scan or a big rmtree must not delay readiness), then every interval while the daemon lives. One bad
    pass (db busy, a raced rmtree) is logged and the loop lives on; the next pass reconciles."""
    delay = SWEEP_STARTUP_DELAY_SECS
    while True:
        await asyncio.sleep(delay)
        delay = SWEEP_INTERVAL_SECS
        try:
            swept = await asyncio.to_thread(_run_sweep, state)
        except (OSError, sqlite3.Error, json.JSONDecodeError) as exc:
            _log(f"attachment sweep failed: {exc}")
            continue
        if swept:
            _log(f"swept {swept} abandoned attachment dirs")


def write_death_notification(notifications_dir: pl.Path) -> None:
    notifications_dir.mkdir(parents=True, exist_ok=True)
    notification = {
        "source": "chat",
        "type": "daemon_died",
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    path = notifications_dir / f"{int(time.time() * 1e6)}-chat-daemon_died.json"
    path.write_text(json.dumps(notification))


async def _socket_server(state: DaemonState) -> None:
    state.sock_path.unlink(missing_ok=True)

    server = await asyncio.start_unix_server(functools.partial(_handle_socket_conn, state), path=str(state.sock_path))
    state.sock_path.chmod(0o600)
    _log(f"socket server: {state.sock_path}")

    try:
        await state.shutdown.wait()
    finally:
        server.close()
        await server.wait_closed()


def _declared(path: str) -> tuple[pl.Path, str]:
    """The file to send and what the node is told it is, after the checks a local file must pass. Runs
    off the loop, since it reaches disk."""
    source = pl.Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(str(source))
    size = source.stat().st_size
    if size > attachments.MAX_ATTACHMENT_BYTES:
        raise attachments.SizeError(f"{source} is {size} bytes, over the {attachments.MAX_ATTACHMENT_BYTES} byte limit")
    guessed = mimetypes.guess_type(source.name)[0]
    return source, guessed if guessed is not None else attachments.FALLBACK_MIME


async def _upload_one(replica: ReplicaState, root: pl.Path, path: str) -> attachments.AttachmentMeta:
    """Move one file to the node and keep a copy under the id the node minted for it, so this agent's
    own history renders the same blob the room holds."""
    source, mime = await asyncio.to_thread(_declared, path)
    meta = await replica.client.upload(source, mime)
    return await asyncio.to_thread(attachments.store_copy, root, source, meta)


async def _upload_attachments(replica: ReplicaState, root: pl.Path, attach: list[str]) -> tuple[list[str], str | None]:
    """Every attachment of one send, uploaded in order, as the ids the message references. A local
    failure fails the whole send with a clear error; copies of a partly failed batch age out to the
    sweep, and the node collects the uploads nothing referenced."""
    if len(attach) > attachments.MAX_ATTACHMENTS_PER_MESSAGE:
        return [], f"at most {attachments.MAX_ATTACHMENTS_PER_MESSAGE} attachments per message"
    ids: list[str] = []
    for path in attach:
        try:
            meta = await _upload_one(replica, root, path)
        except FileNotFoundError:
            return [], f"no such file: {path}"
        except attachments.SizeError as exc:
            return [], str(exc)
        except attachments.UnknownAttachmentError as exc:
            return [], f"the node answered an attachment id this store cannot hold: {exc}"
        except OSError as exc:
            return [], f"cannot read {path}: {exc}"
        ids.append(meta["id"])
    return ids, None


async def _target_room(replica: ReplicaState, room: str | None, to: str | None) -> str:
    """The room a send lands in: the one it names, the peer room with the agent it names (opened when
    the node does not hold it yet), or the conversation with the user."""
    if room is not None:
        return room
    if to is None:
        return direct_room_id(replica.agent)
    opened = await replica.client.open_room([replica.agent, to], None)
    return opened["id"]


def _send_shape_error(message: str, attach: list[str], room: str | None, to: str | None) -> str | None:
    """What refuses a send before the node is dialed: nothing to send, or two rooms named at once."""
    if not message and not attach:
        return "empty message"
    if room is not None and to is not None:
        return "name one room: --room or --to, not both"
    return None


async def _handle_send(state: DaemonState, message: str, attach: list[str], room: str | None, to: str | None) -> dict[str, object]:
    """One send: upload the attachments, then post to the node, which owns the speaking gate and the
    burst guard. The local row is the replica's, which persists the frame the node sends back, so the
    reply is written once however it arrives. `user_speaking` marks the one refusal the sender must
    treat as "floor yielded", not an error: `send` stops the rest of a paced reply on it and exits
    clean."""
    shape_error = _send_shape_error(message, attach, room, to)
    if shape_error is not None:
        return {"error": shape_error}
    if state.replica is None:
        return {"error": NODE_UNREACHABLE}
    try:
        target = await _target_room(state.replica, room, to)
        ids, upload_error = await _upload_attachments(state.replica, state.attachments_root, attach)
        if upload_error is not None:
            return {"error": upload_error}
        node_id = await state.replica.client.post(target, message, ids)
    except SpeakingRefusedError as exc:
        return {"error": str(exc), "user_speaking": True}
    except (BurstRefusedError, NodeError) as exc:
        return {"error": str(exc)}
    return {"ok": True, "message": message, "id": node_id}


async def _handle_socket_conn(state: DaemonState, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        data = await asyncio.wait_for(reader.read(65536), timeout=30.0)
        request = json.loads(data.decode())
        command = request["command"]

        response: dict[str, object]
        if command == "send":
            message = request["message"].strip()
            attach_raw = request["attach"] if "attach" in request else []
            attach = attach_raw if isinstance(attach_raw, list) and all(isinstance(one, str) for one in attach_raw) else None
            if attach is None:
                response = {"error": "attach must be a list of paths"}
            else:
                room = request["room"] if "room" in request else None
                to = request["to"] if "to" in request else None
                response = await _handle_send(state, message, attach, room, to)
        elif command == "status":
            connected = state.replica is not None and state.replica.connected
            response = {"ok": True, "node_connected": connected}
        else:
            response = {"error": f"unknown command: {command}"}

        writer.write(json.dumps(response).encode())
        await writer.drain()
    except (json.JSONDecodeError, KeyError, TimeoutError, OSError) as exc:
        _log(f"socket error: {exc}")
    finally:
        writer.close()
        await writer.wait_closed()


def _starttime(pid: int) -> int | None:
    """Field 22 of /proc/<pid>/stat: the process start time in clock ticks since boot.

    A recycled pid cannot share the original's starttime, because the process that took the pid
    necessarily started later, so (pid, starttime) is a stable identity. Returns None where /proc
    is unreadable, which drops the caller back to a bare pid-existence check.
    """
    try:
        stat = pl.Path(f"/proc/{pid}/stat").read_text()
        # comm is a bracketed field that may itself contain spaces and parentheses, so the
        # numbered fields resume after the LAST ')'.
        return int(stat[stat.rindex(")") + 2 :].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _record(pid: int) -> str:
    """The pid record: "<pid> <starttime>", or a bare pid where the starttime is unavailable.

    A bare pid is the honest form of "identity unknown", and live_pid() reads it the legacy way
    rather than as a mismatch. Writing the string "None" into the record would mean the same thing
    while looking like data.
    """
    started = _starttime(pid)
    return f"{pid} {started}" if started is not None else str(pid)


def live_pid() -> int | None:
    """The recorded pid, but only while it is still the process that was recorded.

    os.kill(pid, 0) answers "does some process hold this pid", never "is this still mine". The
    records outlive the container while a fresh pid namespace renumbers from low values, so a
    reused pid otherwise reads as a healthy daemon, every idempotent start skips it, and the
    channel is silently down while `status` keeps reporting it up.
    """
    try:
        record = PIDFILE.read_text().split()
        pid = int(record[0])
        os.kill(pid, 0)
    except (FileNotFoundError, IndexError, ValueError, ProcessLookupError, PermissionError):
        return None
    # LEGACY(remove-when: no daemon record predating the release that ships this check remains, i.e.
    # every box has restarted its daemons at least once on this version): a record written by the
    # old code is a bare pid. Trust it as before rather than reading the absence of a starttime as a
    # mismatch, because an upgrade must not declare a live daemon dead and let a second stack beside
    # it. Once records have converged, an unparseable second field should read as dead, not as legacy.
    if len(record) > 1 and record[1].isdigit():
        current = _starttime(pid)
        if current is not None and current != int(record[1]):
            return None
    return pid


def _ready(sock_path: pl.Path) -> bool:
    """The daemon is up once its socket answers `status`, which is the surface `chat send` uses, so a
    start that returns hands the caller a socket it can send on."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(PROBE_TIMEOUT_SECS)
            probe.connect(str(sock_path))
            probe.sendall(json.dumps({"command": "status"}).encode())
            probe.shutdown(socket.SHUT_WR)
            answer = json.loads(probe.recv(PROBE_ANSWER_BYTES).decode())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(answer, dict) and "ok" in answer


def _abandon(child: subprocess.Popen[bytes], message: str) -> int:
    """A start that gives up takes its child and its record with it: a daemon nothing can reach, with
    a record that says it is up, reads as running and turns every later start into a no-op."""
    child.terminate()
    try:
        child.wait(timeout=STOP_TIMEOUT_SECS)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
    PIDFILE.unlink(missing_ok=True)
    return _fail(message)


def _await_ready(child: subprocess.Popen[bytes], sock_path: pl.Path) -> int:
    """Holds the start open until the daemon it spawned answers on its socket, which is what lets
    the caller's next line send a message."""
    deadline = time.monotonic() + READY_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if child.poll() is not None:
            return _abandon(child, f"{NAME} exited during startup; see {LOG}")
        if _ready(sock_path):
            print(json.dumps({"status": "started"}))
            return 0
        time.sleep(POLL_SECS)
    return _abandon(child, f"{NAME} never answered on {sock_path}; see {LOG}")


def _claim(pid: int) -> bool:
    try:
        record = os.open(PIDFILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(record, "w") as handle:
        handle.write(_record(pid))
    return True


def _claim_start() -> int | None:
    """Takes the pid record exclusively for this start, so a start that loses the claim answers
    already_running instead of stacking a daemon beside the winner's. A record no process stands
    behind is cleared and taken over, which is the one path on which two starts can both spawn, and
    the duplicate loses on its own resources. None means this start owns the record and everything
    it later removes; anything else is this start's whole answer."""
    if _claim(os.getpid()):
        return None
    deadline = time.monotonic() + CLAIM_WAIT_SECS
    while time.monotonic() < deadline:
        if live_pid() is not None:
            print(json.dumps({"status": "already_running"}))
            return 0
        if not PIDFILE.exists():
            break
        time.sleep(POLL_SECS)
    PIDFILE.unlink(missing_ok=True)
    if _claim(os.getpid()):
        return None
    return _fail(f"another {NAME} start holds {PIDFILE}")


def _start() -> int:
    if live_pid() is not None:
        print(json.dumps({"status": "already_running"}))
        return 0
    DAEMONS_DIR.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    answer = _claim_start()
    if answer is not None:
        return answer
    with LOG.open("ab") as log:
        child = subprocess.Popen(
            [sys.argv[0], "serve"], env={**os.environ, "PYTHONUNBUFFERED": "1"}, start_new_session=True, stdout=log, stderr=log
        )
    PIDFILE.write_text(_record(child.pid))
    return _await_ready(child, _sock_path(default_data_dir()))


def _await_gone(deadline: float) -> bool:
    """Waits out the daemon until a deadline shared with the rest of this stop. Answers whether
    the process the record names is gone."""
    while time.monotonic() < deadline:
        if live_pid() is None:
            return True
        time.sleep(POLL_SECS)
    return live_pid() is None


def _stop() -> int:
    """SIGTERM then, for a daemon that ignored it, SIGKILL, both inside the one stop budget,
    so the verb ends the daemon rather than handing back a record it cannot honour. A daemon
    that exits between the check and the signal is the stop it was asked for, not an error."""
    pid = live_pid()
    if pid is None:
        print(json.dumps({"status": "already_stopped"}))
        return 0
    started = time.monotonic()
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    # Two thirds of the budget in, a daemon that has not honoured SIGTERM is killed instead, and
    # the remainder is what reaps it. Read here, not at import, so the budget in force is the one
    # the caller set.
    if not _await_gone(started + STOP_TIMEOUT_SECS * 2 // 3):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        if not _await_gone(started + STOP_TIMEOUT_SECS):
            return _fail(f"{NAME} still running {STOP_TIMEOUT_SECS}s after SIGTERM then SIGKILL (pid={pid})")
    PIDFILE.unlink(missing_ok=True)
    print(json.dumps({"status": "stopped"}))
    return 0


def _status() -> int:
    """Reads the pid record alone, never vestad, so status answers instantly and truthfully while
    vestad is down. The daemon serves no port, so `port` is always null."""
    print(json.dumps({"running": live_pid() is not None, "port": None}))
    return 0


def daemon_cmd(action: str) -> int:
    if action in ("", "-h", "--help", "help"):
        print(USAGE)
        return 0
    if action == "start":
        return _start()
    if action == "stop":
        return _stop()
    if action == "restart":
        # One verb, one line of output: the stop half is swallowed, and a stop that failed
        # must not be followed by a start onto a daemon that is still there.
        with contextlib.redirect_stdout(io.StringIO()):
            stopped = _stop()
        return _start() if stopped == 0 else stopped
    if action == "status":
        return _status()
    print(USAGE, file=sys.stderr)
    return 1


def _log(message: str) -> None:
    print(f"[chat] {message}", file=sys.stderr, flush=True)
