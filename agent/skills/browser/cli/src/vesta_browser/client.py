"""The one client of the daemon socket: one JSON line out, one JSON line back, over a sync socket.

`cli.py` sends every command through `send`; `daemon.py` reads liveness through `ping`. Neither
opens the socket itself, so the framing lives here alone.
"""

from __future__ import annotations

import json
import socket

from . import protocol as p
from .runtime_paths import Paths

RECV_CHUNK_BYTES = 1 << 16


def _daemon_down(payload: dict[str, p.JsonValue], message: str) -> p.Result:
    err = p.error("daemon_down", "validation", message, retryable=True, suggested_action="run: browser daemon start")
    return p.result(request_id=str(payload["request_id"]), op=str(payload["op"]), ok=False, err=err)


def send(paths: Paths, payload: dict[str, p.JsonValue], timeout: float) -> p.Result:
    """One request, one reply. A socket that is absent, refuses, closes with no answer, or answers
    nothing inside `timeout` is `daemon_down`: the daemon owns every other deadline, so a wait that
    outlasts the caller's budget is a daemon that is not answering."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(paths.socket))
            sock.sendall((json.dumps(payload) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(RECV_CHUNK_BYTES)
                if not chunk:
                    break
                data += chunk
    except OSError as exc:
        return _daemon_down(payload, f"browser daemon not reachable at {paths.socket}: {exc}")
    try:
        result = json.loads(data) if data else None
    except json.JSONDecodeError:
        result = None
    if not isinstance(result, dict):
        return _daemon_down(payload, f"browser daemon closed the connection without an answer at {paths.socket}")
    return result


def ping(paths: Paths, timeout: float) -> bool:
    """Liveness: a daemon that answers `status` is up."""
    return send(paths, p.request("status", "ping"), timeout)["ok"] is True
