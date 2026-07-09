import os
import pathlib
import subprocess
import threading

import pytest

import daemon_lifecycle as dl


def test_pid_roundtrip(tmp_path: pathlib.Path):
    assert dl.read_pid(tmp_path) is None
    dl.write_pid(tmp_path)
    assert dl.read_pid(tmp_path) == os.getpid()
    dl.remove_pid(tmp_path)
    assert dl.read_pid(tmp_path) is None


def test_remove_pid_is_idempotent(tmp_path: pathlib.Path):
    dl.remove_pid(tmp_path)
    dl.remove_pid(tmp_path)


def test_read_pid_ignores_non_numeric_content(tmp_path: pathlib.Path):
    dl.pid_path(tmp_path).write_text("not-a-pid")
    assert dl.read_pid(tmp_path) is None


def test_process_alive_for_self_and_a_dead_pid():
    assert dl.process_alive(os.getpid()) is True
    # A pid far past any plausible live process on a test box.
    assert dl.process_alive(2**30) is False


def test_daemon_running_cleans_up_a_stale_pidfile(tmp_path: pathlib.Path):
    dl.pid_path(tmp_path).write_text(str(2**30))
    running, pid = dl.daemon_running(tmp_path)
    assert running is False
    assert pid is None
    assert dl.read_pid(tmp_path) is None


def test_daemon_running_true_for_a_live_pid(tmp_path: pathlib.Path):
    dl.write_pid(tmp_path)
    running, pid = dl.daemon_running(tmp_path)
    assert running is True
    assert pid == os.getpid()


def test_daemon_info_roundtrip(tmp_path: pathlib.Path):
    assert dl.read_daemon_info(tmp_path) is None
    dl.write_daemon_info(tmp_path, 42)
    info = dl.read_daemon_info(tmp_path)
    assert info is not None
    assert info["interval"] == 42
    assert "started_at" in info


def test_read_daemon_info_returns_none_on_corrupt_json(tmp_path: pathlib.Path):
    dl.daemon_info_path(tmp_path).write_text("{not json")
    assert dl.read_daemon_info(tmp_path) is None


def test_stop_requested_marker_roundtrip(tmp_path: pathlib.Path):
    assert dl.consume_stop_requested(tmp_path) is False
    dl.mark_stop_requested(tmp_path)
    assert dl.consume_stop_requested(tmp_path) is True
    # Consuming clears the marker: a second read finds nothing.
    assert dl.consume_stop_requested(tmp_path) is False


@pytest.mark.parametrize(
    "screen_ls,name,expected",
    [
        ("There are screens on:\n\t123.email-client\t(Detached)\n1 Socket in /run/screen.\n", "email-client", True),
        ("There are screens on:\n\t123.email-client\t(Dead ???)\nRemove dead screens with 'screen -wipe'.\n", "email-client", False),
        ("No Sockets found in /run/screen/S-root.\n", "email-client", False),
        ("There are screens on:\n\t123.email-client-other\t(Detached)\n1 Socket in /run/screen.\n", "email-client", False),
        ("There are screens on:\n\t123.email-client\t(Detached)\n\t456.email-client-watchdog\t(Detached)\n2 Sockets.\n", "email-client", True),
    ],
)
def test_screen_output_has_live_session(screen_ls: str, name: str, expected: bool):
    assert dl.screen_output_has_live_session(screen_ls, name) is expected


@pytest.mark.parametrize(
    "cfg,tok,provider,expected",
    [
        (
            {"user": "a@example.com"},
            None,
            "gmail",
            {"account": "personal", "provider": "gmail", "user": "a@example.com", "auth_configured": False},
        ),
        (
            {"user": "a@example.com"},
            {"app_password": "secret"},
            "generic",
            {"account": "personal", "provider": "generic", "user": "a@example.com", "auth_configured": True},
        ),
        (
            {"user": "a@example.com"},
            {"refresh_token": "rt"},
            "gmail",
            {"account": "personal", "provider": "gmail", "user": "a@example.com", "auth_configured": True},
        ),
        (
            {},
            {"user": "token-user@example.com"},
            "microsoft-personal",
            {"account": "personal", "provider": "microsoft-personal", "user": "token-user@example.com", "auth_configured": False},
        ),
        (
            {"user": "a@example.com"},
            {"app_password": ""},
            "generic",
            {"account": "personal", "provider": "generic", "user": "a@example.com", "auth_configured": False},
        ),
    ],
)
def test_account_auth_summary(cfg: dict, tok: dict | None, provider: str, expected: dict):
    assert dl.account_auth_summary("personal", cfg, tok, provider) == expected


def test_daemon_status_without_running_daemon_or_info(tmp_path: pathlib.Path):
    status = dl.daemon_status(state_dir=tmp_path, accounts=[])
    assert status["running"] is False
    assert status["pid"] is None
    assert status["session"] == dl.SESSION_NAME
    assert status["accounts"] == []
    assert "interval" not in status
    assert "started_at" not in status


def test_daemon_status_includes_interval_and_started_at_when_present(tmp_path: pathlib.Path):
    dl.write_pid(tmp_path)
    dl.write_daemon_info(tmp_path, 30)
    accounts = [{"account": "personal", "provider": "gmail", "user": "a@example.com", "auth_configured": True}]
    status = dl.daemon_status(state_dir=tmp_path, accounts=accounts)
    assert status["running"] is True
    assert status["pid"] == os.getpid()
    assert status["interval"] == 30
    assert status["accounts"] == accounts


def test_daemon_start_is_idempotent_and_never_shells_out_when_already_running(tmp_path: pathlib.Path, monkeypatch):
    dl.write_pid(tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called when the daemon is already running")

    monkeypatch.setattr(subprocess, "run", fail_if_called)
    result = dl.daemon_start(
        state_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        poll_daemon_path=tmp_path / "poll_daemon.py",
        log_path=tmp_path / "poll_daemon.log",
        interval=15,
    )
    assert result == {"status": "already_running", "pid": os.getpid(), "session": dl.SESSION_NAME}


def test_daemon_stop_is_idempotent_when_already_stopped(tmp_path: pathlib.Path):
    result = dl.daemon_stop(state_dir=tmp_path)
    assert result == {"status": "already_stopped", "session": dl.SESSION_NAME}


def test_daemon_stop_marks_stop_requested_and_sends_sigterm_to_a_live_pid(tmp_path: pathlib.Path):
    proc = subprocess.Popen(["sleep", "30"])
    try:
        dl.pid_path(tmp_path).write_text(str(proc.pid))
        result_holder: dict = {}

        def run_stop():
            result_holder["result"] = dl.daemon_stop(state_dir=tmp_path)

        # daemon_stop polls os.kill(pid, 0) for liveness, which reports a terminated
        # child as still alive until this process (its parent) reaps it; run the stop
        # on a thread so the main thread's proc.wait() can reap it as soon as it exits.
        stopper = threading.Thread(target=run_stop)
        stopper.start()
        proc.wait(timeout=5)
        stopper.join(timeout=5)

        result = result_holder["result"]
        assert result["status"] == "stopped"
        assert result["pid"] == proc.pid
        # `sleep 30` never consumes the marker itself (only poll_daemon.py's own
        # shutdown does), so it is still there for the real daemon to read.
        assert dl.consume_stop_requested(tmp_path) is True
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_daemon_restart_reuses_the_last_interval_when_not_overridden(tmp_path: pathlib.Path, monkeypatch):
    dl.write_daemon_info(tmp_path, 45)
    started_with = {}

    def fake_start(**kwargs):
        started_with["interval"] = kwargs["interval"]
        return {"status": "started", "pid": 1, "session": dl.SESSION_NAME}

    monkeypatch.setattr(dl, "daemon_start", fake_start)
    result = dl.daemon_restart(
        state_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        poll_daemon_path=tmp_path / "poll_daemon.py",
        log_path=tmp_path / "poll_daemon.log",
        interval=None,
    )
    assert result["status"] == "started"
    assert started_with["interval"] == 45


def test_daemon_restart_prefers_an_explicit_interval_override(tmp_path: pathlib.Path, monkeypatch):
    dl.write_daemon_info(tmp_path, 45)
    started_with = {}

    def fake_start(**kwargs):
        started_with["interval"] = kwargs["interval"]
        return {"status": "started", "pid": 1, "session": dl.SESSION_NAME}

    monkeypatch.setattr(dl, "daemon_start", fake_start)
    dl.daemon_restart(
        state_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        poll_daemon_path=tmp_path / "poll_daemon.py",
        log_path=tmp_path / "poll_daemon.log",
        interval=5,
    )
    assert started_with["interval"] == 5


def test_daemon_restart_propagates_a_stop_failure_without_starting(tmp_path: pathlib.Path, monkeypatch):
    monkeypatch.setattr(dl, "daemon_stop", lambda *, state_dir: {"error": "still running"})

    def fail_if_called(**kwargs):
        raise AssertionError("daemon_start should not run when stop failed")

    monkeypatch.setattr(dl, "daemon_start", fail_if_called)
    result = dl.daemon_restart(
        state_dir=tmp_path,
        runtime_dir=tmp_path / "runtime",
        poll_daemon_path=tmp_path / "poll_daemon.py",
        log_path=tmp_path / "poll_daemon.log",
        interval=None,
    )
    assert result == {"error": "still running"}
