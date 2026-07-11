"""Lifecycle for the voice-server screen daemon.

`start` owns the register-service call (idempotent: vestad returns the same port for a
given name on every call), so the agent runs one command instead of stitching together
register-service + screen by hand. Liveness is a TCP connect to the registered port;
voice-server has no admin socket of its own.
"""

import os
import pathlib as pl
import re
import shutil
import socket
import subprocess
import time
import typing as tp

from . import config as vc

SESSION_NAME = "voice"
START_TIMEOUT_S = 30
STOP_TIMEOUT_S = 15
POLL_INTERVAL_S = 1.0
PORT_CONNECT_TIMEOUT_S = 2.0

REGISTER_SERVICE = pl.Path.home() / "agent" / "skills" / "service" / "scripts" / "register-service"


class DaemonError(RuntimeError):
    pass


class AuthEntry(tp.TypedDict):
    provider: str
    enabled: bool


class LifecycleResult(tp.TypedDict):
    status: str
    session: str
    port: int


class StatusResult(tp.TypedDict):
    running: bool
    session: str
    port: int
    auth: dict[str, AuthEntry | None]


def data_dir() -> pl.Path:
    return pl.Path.home() / ".voice"


def screen_output_has_live_session(screen_ls: str, name: str) -> bool:
    """A LIVE screen session with exactly this name (a "(Dead ???)" corpse does not count)."""
    pattern = re.compile(r"\d+\." + re.escape(name) + r"\s")
    for line in screen_ls.splitlines():
        if pattern.search(line) and "Dead" not in line:
            return True
    return False


def _screen_session_live(name: str) -> bool:
    # `screen -ls` exits nonzero when no sessions exist; only the output matters.
    result = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
    return screen_output_has_live_session(result.stdout, name)


def resolve_port() -> int:
    result = subprocess.run([str(REGISTER_SERVICE), "voice"], capture_output=True, text=True, timeout=35)
    if result.returncode != 0 or not result.stdout.strip():
        raise DaemonError(f"register-service failed: {result.stderr.strip()}")
    return int(result.stdout.strip())


def port_alive(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=PORT_CONNECT_TIMEOUT_S):
            return True
    except OSError:
        return False


def _auth_status() -> dict[str, AuthEntry | None]:
    cfg = vc.load(data_dir())
    auth: dict[str, AuthEntry | None] = {}
    for domain in ("stt", "tts"):
        entry = cfg[domain]
        if entry is None or "provider" not in entry:
            auth[domain] = None
            continue
        enabled = entry["enabled"] if "enabled" in entry else False
        auth[domain] = {"provider": entry["provider"], "enabled": enabled}
    return auth


def start() -> LifecycleResult:
    port = resolve_port()
    if port_alive(port):
        return {"status": "already_running", "session": SESSION_NAME, "port": port}

    binary = shutil.which("voice-server")
    if binary is None:
        raise DaemonError("voice-server binary not on PATH; run `uv tool install --editable ~/agent/skills/voice/cli` first")

    env = dict(os.environ)
    env["SKILL_PORT"] = str(port)
    launch = subprocess.run(["screen", "-dmS", SESSION_NAME, binary], env=env, capture_output=True, text=True)
    if launch.returncode != 0:
        raise DaemonError(f"failed to launch screen session: {launch.stderr.strip()}")

    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if port_alive(port):
            return {"status": "started", "session": SESSION_NAME, "port": port}
        if not _screen_session_live(SESSION_NAME):
            raise DaemonError("voice-server exited during startup; run 'voice-server' in the foreground to see the error")
        time.sleep(POLL_INTERVAL_S)
    raise DaemonError(f"voice-server did not answer on port {port} within {START_TIMEOUT_S}s")


def stop() -> LifecycleResult:
    port = resolve_port()
    if not port_alive(port):
        return {"status": "already_stopped", "session": SESSION_NAME, "port": port}

    subprocess.run(["screen", "-S", SESSION_NAME, "-X", "quit"])
    deadline = time.monotonic() + STOP_TIMEOUT_S
    while time.monotonic() < deadline:
        if not port_alive(port):
            return {"status": "stopped", "session": SESSION_NAME, "port": port}
        time.sleep(POLL_INTERVAL_S)
    raise DaemonError(f"voice-server still answering on port {port} after screen quit; inspect with 'screen -r {SESSION_NAME}'")


def restart() -> LifecycleResult:
    stop()
    result = start()
    result["status"] = "restarted"
    return result


def status() -> StatusResult:
    port = resolve_port()
    return {
        "running": port_alive(port),
        "session": SESSION_NAME,
        "port": port,
        "auth": _auth_status(),
    }
