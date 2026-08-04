"""Admin lifecycle tests that don't require a live daemon."""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
from vesta_browser import admin, daemon, launcher

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


class _StopSpawnError(Exception):
    """Sentinel so a test stops at the spawn boundary without starting a real daemon."""


def _stop_spawn(*args, **kwargs):
    raise _StopSpawnError


def _stale_guard_setup(tmp_path, monkeypatch, *, pid_alive):
    monkeypatch.setattr(admin, "SESSION_FILE_PREFIX", f"{tmp_path}/")
    monkeypatch.setattr(admin, "daemon_healthy", lambda s: False)
    monkeypatch.setattr(admin, "daemon_alive", lambda s: False)
    monkeypatch.setattr(admin, "_pid_alive", lambda pid: pid_alive)
    monkeypatch.setattr(admin.subprocess, "Popen", _stop_spawn)
    monkeypatch.delenv("VESTA_BROWSER_CDP_WS", raising=False)
    monkeypatch.delenv("VESTA_BROWSER_BIDI_WS", raising=False)


def test_ensure_daemon_rejects_stale_recorded_endpoint(tmp_path, monkeypatch):
    """A recorded ws url outlives the browser it points at (the files live in /tmp and survive a
    container restart). ensure_daemon must notice the recorded pid is dead and say so, instead of
    handing the daemon a dead port and surfacing an opaque connection error."""
    session = "stale-endpoint"
    _stale_guard_setup(tmp_path, monkeypatch, pid_alive=False)
    (tmp_path / f"{session}.browser-pid").write_text("4216")
    (tmp_path / f"{session}.bidi-ws").write_text("ws://127.0.0.1:38125/session")

    with pytest.raises(RuntimeError) as excinfo:
        admin.ensure_daemon(wait_s=0.1, name=session)

    message = str(excinfo.value)
    assert "stale" in message
    assert "browser launch" in message
    assert "4216" in message, "name the dead pid so the cause is checkable"
    assert not (tmp_path / f"{session}.bidi-ws").exists(), "the stale ws url must be cleared"


def test_ensure_daemon_keeps_endpoint_when_browser_is_alive(tmp_path, monkeypatch):
    """The guard must only fire on a dead browser. A live one keeps its recorded endpoint."""
    session = "live-endpoint"
    _stale_guard_setup(tmp_path, monkeypatch, pid_alive=True)
    (tmp_path / f"{session}.browser-pid").write_text("4216")
    (tmp_path / f"{session}.bidi-ws").write_text("ws://127.0.0.1:38125/session")

    # Reaching the spawn is the point: no stale-endpoint error was raised.
    with contextlib.suppress(_StopSpawnError):
        admin.ensure_daemon(wait_s=0.1, name=session)
    assert (tmp_path / f"{session}.bidi-ws").exists(), "a live browser must keep its endpoint"


def test_connect_endpoint_survives_a_dead_launch_pid(tmp_path, monkeypatch):
    """Recording a connect endpoint over a dead launch's records must clear the launch's
    browser-pid, so the stale-pid guard never reads the dead pid and clears a still-valid
    connect endpoint or raises the stale error."""
    session = "connect-after-dead-launch"
    _stale_guard_setup(tmp_path, monkeypatch, pid_alive=False)
    (tmp_path / f"{session}.browser-pid").write_text("4216")
    admin.record_cdp_endpoint("ws://127.0.0.1:9222/devtools/browser/abc", session)

    # Reaching the spawn is the point: the guard did not fire on the dead launch pid.
    with contextlib.suppress(_StopSpawnError):
        admin.ensure_daemon(wait_s=0.1, name=session)
    assert (tmp_path / f"{session}.cdp-ws").exists(), "a connect endpoint must survive the stale-pid guard"


def test_launch_records_replace_a_connect_era_endpoint(tmp_path, monkeypatch):
    """launch_browser must clear a prior connect's cdp-ws before recording its own pid + bidi-ws:
    a surviving cdp-ws would win endpoint precedence over the launched browser, and the recorded
    pid would let the stale-pid guard clear that unrelated endpoint once the pid dies."""
    session = "launch-after-connect"
    monkeypatch.setattr(admin, "SESSION_FILE_PREFIX", f"{tmp_path}/")
    (tmp_path / f"{session}.cdp-ws").write_text("ws://127.0.0.1:9222/devtools/browser/abc")
    running = launcher.RunningCamoufox(pid=4216, ws_url="ws://127.0.0.1:38125/session", user_data_dir=tmp_path, exe_path="camoufox", proc=None)
    monkeypatch.setattr(admin, "launch", lambda **kwargs: running)

    assert admin.launch_browser(session) is running

    assert not (tmp_path / f"{session}.cdp-ws").exists(), "a connect-era cdp endpoint must not outlive a launch"
    assert (tmp_path / f"{session}.bidi-ws").read_text() == "ws://127.0.0.1:38125/session"
    assert (tmp_path / f"{session}.browser-pid").read_text() == "4216"


def _profile_tree(root, name, *, size=32):
    d = root / name
    d.mkdir(parents=True)
    (d / "prefs.js").write_bytes(b"x" * size)
    return d


def _isolate_roots(tmp_path, monkeypatch, *, live=()):
    """Point both profile roots at tmp_path and stub the /proc liveness scan."""
    monkeypatch.setattr(admin, "PROFILE_ROOT", tmp_path / "profile")
    monkeypatch.setattr(admin, "EPHEMERAL_ROOT", tmp_path / "ephemeral")
    monkeypatch.setattr(admin, "_profile_has_live_owner", lambda d: d.name in live)


def test_prune_reports_without_deleting(tmp_path, monkeypatch):
    """Default is a dry run: it reports reclaimable dirs and leaves them on disk."""
    _isolate_roots(tmp_path, monkeypatch)
    stale = _profile_tree(tmp_path / "ephemeral", "crashed-session")

    out = admin.prune_profiles()

    assert out["applied"] is False
    assert [e["name"] for e in out["removable"]] == ["crashed-session"]
    assert out["reclaimable_bytes"] == 32
    assert out["removed"] == []
    assert stale.exists()


def test_prune_never_touches_durable_profiles(tmp_path, monkeypatch):
    """A durable --user-data-dir profile is idle, not orphaned, and must survive --yes.

    Regression: an earlier design pruned anything under ~/.browser with no live owner,
    which deleted a signed-in profile the agent meant to reuse. Liveness cannot recover
    intent, so scope is the ephemeral root and nothing else.
    """
    _isolate_roots(tmp_path, monkeypatch)
    shared = _profile_tree(tmp_path, "profile")
    durable = _profile_tree(tmp_path, "work")  # ~/.browser/work, signed in, idle
    stale = _profile_tree(tmp_path / "ephemeral", "crashed-session")

    out = admin.prune_profiles(apply=True)

    assert durable.exists(), "a durable profile must never be pruned"
    assert shared.exists()
    assert not stale.exists()
    assert [e["name"] for e in out["removed"]] == ["crashed-session"]


def test_prune_keeps_running_ephemeral_session(tmp_path, monkeypatch):
    """A live ephemeral session is never pulled out from under itself."""
    _isolate_roots(tmp_path, monkeypatch, live=("in-use",))
    live = _profile_tree(tmp_path / "ephemeral", "in-use")
    stale = _profile_tree(tmp_path / "ephemeral", "crashed-session")

    out = admin.prune_profiles(apply=True)

    assert live.exists() and not stale.exists()
    assert [e["name"] for e in out["kept"]] == ["in-use"]
    assert out["kept"][0]["reason"] == "live owner"


def test_prune_healthy_case_is_unambiguous(tmp_path, monkeypatch):
    """With nothing to clean it says so plainly, and still names what it walked."""
    _isolate_roots(tmp_path, monkeypatch)

    out = admin.prune_profiles()

    assert out["reclaimable_bytes"] == 0
    assert out["removable"] == [] and out["kept"] == []
    assert out["root"] == str(tmp_path / "ephemeral")


def test_shutdown_removes_only_the_ephemeral_profile(tmp_path, monkeypatch):
    """Stopping a session deletes its throwaway profile, fixing the leak at the source."""
    _isolate_roots(tmp_path, monkeypatch)
    monkeypatch.setenv("BROWSER_SESSION", "scrape")
    monkeypatch.setattr(admin, "restart_daemon", lambda *a, **k: None)
    monkeypatch.setattr(admin, "stop_browser", lambda *a, **k: None)
    ephemeral = _profile_tree(tmp_path / "ephemeral", "scrape")
    durable = _profile_tree(tmp_path, "work")

    admin.shutdown()

    assert not ephemeral.exists()
    assert durable.exists()


def test_shutdown_is_fine_without_an_ephemeral_profile(tmp_path, monkeypatch):
    """The common case (shared profile, nothing to remove) must not raise."""
    _isolate_roots(tmp_path, monkeypatch)
    monkeypatch.setenv("BROWSER_SESSION", "default")
    monkeypatch.setattr(admin, "restart_daemon", lambda *a, **k: None)
    monkeypatch.setattr(admin, "stop_browser", lambda *a, **k: None)

    admin.shutdown()  # must not raise


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="liveness scan reads /proc")
def test_live_owner_is_detected_from_the_real_launch_argv(tmp_path):
    """The /proc scan must recognise a process launched with the real argv builder.

    Every other prune test stubs `_profile_has_live_owner`, so nothing else pins the
    matcher to the argv `launch` actually spawns. If they drift, a live session reads
    as orphaned and `prune --yes` deletes its profile out from under it, with the
    stubbed tests still green.
    """
    exe = tmp_path / "camoufox"
    exe.write_text("#!/bin/sh\nsleep 30\n")
    exe.chmod(0o755)
    mine = tmp_path / "in-use"
    mine.mkdir()
    other = tmp_path / "not-in-use"
    other.mkdir()

    proc = subprocess.Popen(
        launcher._camoufox_argv(str(exe), mine),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + HANG_GUARD_S
        while time.monotonic() < deadline:
            if launcher._profile_has_live_owner(mine):
                break
            time.sleep(0.05)
        else:
            pytest.fail("a running Camoufox was not detected as the profile's live owner")
        assert not launcher._profile_has_live_owner(other)
    finally:
        proc.terminate()
        proc.wait(timeout=HANG_GUARD_S)

    assert not launcher._profile_has_live_owner(mine)
