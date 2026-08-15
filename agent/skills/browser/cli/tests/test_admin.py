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


def test_pid_alive_false_for_none():
    assert admin._pid_alive(None) is False


def test_pid_alive_false_for_a_real_zombie():
    """A dead child its parent never reaped lingers in the pid table and still answers a signal-0
    probe; the shared predicate must read it as dead, since a zombie backend can serve nothing."""
    proc = subprocess.Popen(["true"])
    try:
        deadline = time.monotonic() + HANG_GUARD_S
        while time.monotonic() < deadline and admin._pid_alive(proc.pid):
            time.sleep(0.02)
        assert admin._pid_alive(proc.pid) is False, "zombie still reported alive"
        os.kill(proc.pid, 0)  # a signal-0 probe still succeeds on the corpse
    finally:
        proc.wait()


def test_pid_alive_reads_the_state_past_a_comm_holding_spaces_and_parens(tmp_path, monkeypatch):
    # /proc/<pid>/stat's comm field is unescaped, so splitting on whitespace misreads the state.
    (tmp_path / "42").mkdir()
    (tmp_path / "42" / "stat").write_text("42 (odd ) name Z) R 1 1 0 0 -1 0 0 0")
    monkeypatch.setattr(admin, "PROC", tmp_path)
    assert admin._pid_alive(42) is True


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


def _spawn_orphan_sleep() -> int:
    """A sleep with no living parent in this process tree, so init reaps it the moment it dies:
    the shape of a browser recorded by an earlier CLI invocation."""
    out = subprocess.run(["sh", "-c", "sleep 60 & echo $!"], capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def test_recording_a_new_backend_terminates_the_replaced_live_browser(tmp_path, monkeypatch):
    """The records describe exactly one backend, so recording a connect endpoint over a launched
    browser must terminate the old process: a cleared pid with nothing pointing at it would keep
    a headless browser running invisibly forever."""
    session = "replace-live"
    monkeypatch.setattr(admin, "SESSION_FILE_PREFIX", f"{tmp_path}/")
    pid = _spawn_orphan_sleep()
    try:
        (tmp_path / f"{session}.browser-pid").write_text(str(pid))
        (tmp_path / f"{session}.bidi-ws").write_text("ws://127.0.0.1:38125/session")

        admin.record_cdp_endpoint("ws://127.0.0.1:9222/devtools/browser/abc", session)

        deadline = time.monotonic() + HANG_GUARD_S
        while time.monotonic() < deadline and admin._pid_alive(pid):
            time.sleep(0.05)
        assert not admin._pid_alive(pid), "the replaced browser was left running"
        assert not (tmp_path / f"{session}.browser-pid").exists()
        assert (tmp_path / f"{session}.cdp-ws").read_text() == "ws://127.0.0.1:9222/devtools/browser/abc"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def test_recording_over_a_dead_pid_record_stays_quiet(tmp_path, monkeypatch):
    """A recorded pid whose process is already gone is cleared with no termination attempt."""
    session = "replace-dead"
    monkeypatch.setattr(admin, "SESSION_FILE_PREFIX", f"{tmp_path}/")
    reaped = subprocess.Popen(["true"])
    reaped.wait()
    terminated: list[int] = []
    monkeypatch.setattr(admin, "_terminate_pid", terminated.append)
    (tmp_path / f"{session}.browser-pid").write_text(str(reaped.pid))

    admin.record_bidi_endpoint("ws://127.0.0.1:38125/session", session)

    assert terminated == []
    assert not (tmp_path / f"{session}.browser-pid").exists()
    assert (tmp_path / f"{session}.bidi-ws").read_text() == "ws://127.0.0.1:38125/session"


def test_stop_browser_terminates_the_recorded_browser_and_clears_records(tmp_path, monkeypatch):
    session = "stop-live"
    monkeypatch.setattr(admin, "SESSION_FILE_PREFIX", f"{tmp_path}/")
    pid = _spawn_orphan_sleep()
    try:
        (tmp_path / f"{session}.browser-pid").write_text(str(pid))
        admin.stop_browser(session)
        assert not admin._pid_alive(pid)
        assert not (tmp_path / f"{session}.browser-pid").exists()
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


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


# ── Dead-record reaping ────────────────────────────────────────


def _record_root_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "SESSION_ROOT", tmp_path)
    monkeypatch.setattr(admin, "SESSION_FILE_PREFIX", f"{tmp_path}/vesta-browser-")
    monkeypatch.setattr(admin, "socket_path", lambda name=None: str(tmp_path / f"vesta-browser-{name}.sock"))
    monkeypatch.setattr(admin, "pid_path", lambda name=None: str(tmp_path / f"vesta-browser-{name}.pid"))
    monkeypatch.setattr(admin, "log_path", lambda name=None: str(tmp_path / f"vesta-browser-{name}.log"))


def test_list_sessions_reaps_a_fully_dead_record(tmp_path, monkeypatch):
    """A record whose browser and daemon are both dead describes nothing running: it is
    removed, not listed, so stale metadata never reads as a leaking browser."""
    _record_root_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(admin, "daemon_alive", lambda name=None: False)
    dead = tmp_path / "vesta-browser-crashed.browser-pid"
    dead.write_text(str(2**31 - 1))
    (tmp_path / "vesta-browser-crashed.bidi-ws").write_text("ws://127.0.0.1:1/session")
    live = tmp_path / "vesta-browser-working.browser-pid"
    live.write_text(str(os.getpid()))

    sessions = admin.list_sessions()

    assert [s["name"] for s in sessions] == ["working"]
    assert not dead.exists(), "the dead record is reaped"
    assert not (tmp_path / "vesta-browser-crashed.bidi-ws").exists(), "its endpoint goes with it"
    assert live.exists(), "a live session keeps its record"


def test_list_sessions_keeps_a_dead_browser_under_a_live_daemon(tmp_path, monkeypatch):
    _record_root_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(admin, "daemon_alive", lambda name=None: True)
    record = tmp_path / "vesta-browser-half.browser-pid"
    record.write_text(str(2**31 - 1))

    sessions = admin.list_sessions()

    assert [s["name"] for s in sessions] == ["half"]
    assert sessions[0]["browser_alive"] is False
    assert record.exists()


# ── Startup under contention ───────────────────────────────────


class _LingeringProc:
    """A daemon spawn that never becomes ready and never exits on its own."""

    pid = 4242

    def poll(self):
        return None


def _startup_setup(tmp_path, monkeypatch, *, other_sessions):
    _record_root_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(admin, "daemon_healthy", lambda name=None: False)
    monkeypatch.setattr(admin, "daemon_alive", lambda name=None: False)
    monkeypatch.setattr(admin, "list_sessions", lambda: other_sessions)
    monkeypatch.setattr(admin.subprocess, "Popen", lambda *a, **kw: _LingeringProc())
    monkeypatch.setenv("VESTA_BROWSER_BIDI_WS", "ws://127.0.0.1:1/session")


def test_ensure_daemon_timeout_fails_closed(tmp_path, monkeypatch):
    """A daemon that misses its deadline is killed and its records removed, so a
    half-started one never lingers to confuse the next attempt."""
    _startup_setup(tmp_path, monkeypatch, other_sessions=[])
    killed = []
    monkeypatch.setattr(admin, "_terminate_pid", killed.append)
    (tmp_path / "vesta-browser-solo.sock").write_text("")
    (tmp_path / "vesta-browser-solo.pid").write_text("4242")

    with pytest.raises(RuntimeError) as excinfo:
        admin.ensure_daemon(wait_s=0.05, name="solo")

    assert killed == [4242]
    assert not (tmp_path / "vesta-browser-solo.sock").exists()
    assert not (tmp_path / "vesta-browser-solo.pid").exists()
    assert "contend" not in str(excinfo.value), "no contention hint when starting alone"


def test_ensure_daemon_timeout_names_contention_and_extends_the_budget(tmp_path, monkeypatch):
    """Under fan-out the handshake competes for CPU: the wait scales up and the error
    names the competing sessions plus the http_get fallback."""
    _startup_setup(
        tmp_path,
        monkeypatch,
        other_sessions=[{"name": "research-2", "browser_alive": True, "daemon_alive": False}],
    )
    monkeypatch.setattr(admin, "_terminate_pid", lambda pid: None)

    start = time.monotonic()
    with pytest.raises(RuntimeError) as excinfo:
        admin.ensure_daemon(wait_s=0.05, name="research-1")

    message = str(excinfo.value)
    assert "research-2" in message
    assert "http_get" in message
    assert time.monotonic() - start >= 0.05 * admin.CONTENDED_STARTUP_MULTIPLIER


def test_ensure_daemon_accepts_a_concurrent_spawns_daemon(tmp_path, monkeypatch):
    """Two commands racing to start the same session: ours exits with "already running"
    while the winner's daemon answers. Healthy is healthy, whoever started it."""
    _startup_setup(tmp_path, monkeypatch, other_sessions=[])
    # Answer False for the entry check and the wait loop, True only for the post-loop
    # recheck, so the pass is proven to come from that recheck.
    healthy_answers = iter([False, False, True])
    monkeypatch.setattr(admin, "daemon_healthy", lambda name=None: next(healthy_answers, True))

    class _LostRaceProc:
        pid = 4242

        def poll(self):
            return 0

    monkeypatch.setattr(admin.subprocess, "Popen", lambda *a, **kw: _LostRaceProc())
    killed = []
    monkeypatch.setattr(admin, "_terminate_pid", killed.append)

    admin.ensure_daemon(wait_s=0.05, name="raced")

    assert killed == [], "the winner's daemon must not be killed"
