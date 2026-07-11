#!/usr/bin/env python3
"""Poll-daemon lifecycle: pidfile, stop-requested marker, daemon-info.

Owns the on-disk contract the `email-client daemon start|stop|restart|status`
subcommand and ``poll_daemon.py`` share, so the 130-char screen invocation
lives in exactly one place (``daemon_start``) instead of being copy-pasted
across SETUP.md. The stop-requested marker is how a deliberate ``daemon
stop``/``restart`` tells the daemon's own shutdown not to fire the
``daemon_died`` notification the agent would otherwise investigate.

Has no dependency on ``imap_tools``/``msal`` so its logic (pidfile parsing,
screen-session parsing, auth-summary assembly) can be unit tested without the
account skill's runtime environment. ``daemon_start``/``stop``/``restart``
shell out to ``screen`` and are exercised on a real box.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import signal
import subprocess
import time
from datetime import UTC, datetime

SESSION_NAME = "email-client"
DEFAULT_POLL_INTERVAL_SECS = 15
START_TIMEOUT_SECS = 20
STOP_TIMEOUT_SECS = 15
POLL_INTERVAL_SECS = 0.5


def pid_path(state_dir: pathlib.Path) -> pathlib.Path:
    return state_dir / "daemon.pid"


def daemon_info_path(state_dir: pathlib.Path) -> pathlib.Path:
    return state_dir / "daemon-info.json"


def stop_requested_path(state_dir: pathlib.Path) -> pathlib.Path:
    return state_dir / "stop-requested"


def write_pid(state_dir: pathlib.Path) -> None:
    pid_path(state_dir).write_text(str(os.getpid()))


def remove_pid(state_dir: pathlib.Path) -> None:
    pid_path(state_dir).unlink(missing_ok=True)


def read_pid(state_dir: pathlib.Path) -> int | None:
    p = pid_path(state_dir)
    if not p.exists():
        return None
    raw = p.read_text().strip()
    if not raw.isdigit():
        return None
    return int(raw)


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def daemon_running(state_dir: pathlib.Path) -> tuple[bool, int | None]:
    """Return ``(running, pid)``, cleaning up a stale pidfile left by a crash."""
    pid = read_pid(state_dir)
    if pid is None:
        return False, None
    if process_alive(pid):
        return True, pid
    remove_pid(state_dir)
    return False, None


def write_daemon_info(state_dir: pathlib.Path, interval: int) -> None:
    info = {"interval": interval, "started_at": datetime.now(UTC).replace(microsecond=0).isoformat()}
    daemon_info_path(state_dir).write_text(json.dumps(info))


def read_daemon_info(state_dir: pathlib.Path) -> dict | None:
    p = daemon_info_path(state_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def mark_stop_requested(state_dir: pathlib.Path) -> None:
    stop_requested_path(state_dir).write_text("")


def consume_stop_requested(state_dir: pathlib.Path) -> bool:
    """Return True and clear the marker if the exit was requested via `daemon stop`/`restart`."""
    p = stop_requested_path(state_dir)
    if not p.exists():
        return False
    p.unlink(missing_ok=True)
    return True


def screen_output_has_live_session(screen_ls: str, name: str) -> bool:
    """True iff ``screen -ls`` output has a LIVE session named exactly ``name``.

    A "(Dead ???)" corpse from a previous boot does not count, and ``email-client``
    must not match a differently-named session that merely starts with it.
    """
    pattern = re.compile(r"[0-9]+\." + re.escape(name) + r"\s")
    for line in screen_ls.splitlines():
        if pattern.search(line) and "Dead" not in line:
            return True
    return False


def screen_session_live(name: str = SESSION_NAME) -> bool:
    # `screen -ls` exits nonzero when no sessions exist; only the output matters.
    result = subprocess.run(["screen", "-ls"], capture_output=True, text=True, check=False)
    return screen_output_has_live_session(result.stdout, name)


def account_auth_summary(account: str, cfg: dict, tok: dict | None, provider: str) -> dict:
    """Assemble one account's auth health from already-loaded config/token dicts.

    Pure and network-free: reports whether a usable credential is on disk
    (an app password or an OAuth refresh token), not a live IMAP login.
    """
    if tok is None:
        return {"account": account, "provider": provider, "user": cfg["user"] if "user" in cfg else None, "auth_configured": False}
    auth_configured = bool(tok["app_password"]) if "app_password" in tok else bool(tok["refresh_token"]) if "refresh_token" in tok else False
    user = cfg["user"] if "user" in cfg else (tok["user"] if "user" in tok else None)
    return {"account": account, "provider": provider, "user": user, "auth_configured": auth_configured}


def daemon_start(
    *,
    state_dir: pathlib.Path,
    runtime_dir: pathlib.Path,
    poll_daemon_path: pathlib.Path,
    log_path: pathlib.Path,
    interval: int,
) -> dict:
    """Launch the poll daemon under screen. Idempotent: a live daemon is a no-op."""
    running, pid = daemon_running(state_dir)
    if running:
        return {"status": "already_running", "pid": pid, "session": SESSION_NAME}
    if screen_session_live():
        # A pidfile-less daemon (launched by a raw screen line before this CLI existed)
        # is still running; `screen -dmS` would stack a second poller next to it.
        return {"error": f"a live '{SESSION_NAME}' screen session has no pidfile; quit it with `screen -S {SESSION_NAME} -X quit`, then retry"}
    stop_requested_path(state_dir).unlink(missing_ok=True)
    command = f"cd {runtime_dir} && PYTHONUNBUFFERED=1 uv run python3 {poll_daemon_path} --interval {interval} > {log_path} 2>&1"
    subprocess.run(["screen", "-dmS", SESSION_NAME, "bash", "-c", command], check=True)
    deadline = time.monotonic() + START_TIMEOUT_SECS
    while time.monotonic() < deadline:
        running, pid = daemon_running(state_dir)
        if running:
            return {"status": "started", "pid": pid, "session": SESSION_NAME}
        if not screen_session_live():
            return {"error": f"daemon exited during startup; check {log_path}"}
        time.sleep(POLL_INTERVAL_SECS)
    return {"error": f"daemon did not report a pid within {START_TIMEOUT_SECS}s"}


def daemon_stop(*, state_dir: pathlib.Path) -> dict:
    """Stop the poll daemon: mark the stop intentional, then SIGTERM and wait for exit."""
    running, pid = daemon_running(state_dir)
    if not running:
        return {"status": "already_stopped", "session": SESSION_NAME}
    mark_stop_requested(state_dir)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        stop_requested_path(state_dir).unlink(missing_ok=True)
        remove_pid(state_dir)
        return {"status": "already_stopped", "session": SESSION_NAME}
    deadline = time.monotonic() + STOP_TIMEOUT_SECS
    while time.monotonic() < deadline:
        still_running, _ = daemon_running(state_dir)
        if not still_running:
            return {"status": "stopped", "pid": pid, "session": SESSION_NAME}
        time.sleep(POLL_INTERVAL_SECS)
    return {"error": f"daemon still running {STOP_TIMEOUT_SECS}s after SIGTERM (pid={pid})"}


def daemon_restart(
    *,
    state_dir: pathlib.Path,
    runtime_dir: pathlib.Path,
    poll_daemon_path: pathlib.Path,
    log_path: pathlib.Path,
    interval: int | None,
) -> dict:
    """Stop then start, reusing the daemon's last ``--interval`` unless overridden."""
    use_interval = interval
    if use_interval is None:
        info = read_daemon_info(state_dir)
        use_interval = info["interval"] if info is not None else DEFAULT_POLL_INTERVAL_SECS
    stop_result = daemon_stop(state_dir=state_dir)
    if "error" in stop_result:
        return stop_result
    return daemon_start(
        state_dir=state_dir,
        runtime_dir=runtime_dir,
        poll_daemon_path=poll_daemon_path,
        log_path=log_path,
        interval=use_interval,
    )


def daemon_status(*, state_dir: pathlib.Path, accounts: list[dict]) -> dict:
    running, pid = daemon_running(state_dir)
    info = read_daemon_info(state_dir)
    result: dict = {"running": running, "pid": pid, "session": SESSION_NAME, "accounts": accounts}
    if info is not None:
        result["interval"] = info["interval"]
        result["started_at"] = info["started_at"]
    return result


if __name__ == "__main__":
    raise SystemExit("daemon_lifecycle.py is a library; run the `email-client daemon` subcommand instead")
