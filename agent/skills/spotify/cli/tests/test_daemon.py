"""The spotify daemon owns the four verbs itself: an exclusive pid-record claim, a detached
watcher, SIGTERM as the deliberate stop, and a status read from the record alone. The watcher
serves nothing, so it registers no vestad port and its status port is always null."""

import json
import os
import signal
import types

import pytest
from spotify_cli import daemon


@pytest.fixture
def records(tmp_path, monkeypatch):
    """Redirects the pid record and the log into a tmpdir, the way a hermetic HOME would."""
    daemons_dir = tmp_path / "daemons"
    daemons_dir.mkdir()
    monkeypatch.setattr(daemon, "DAEMONS_DIR", daemons_dir)
    monkeypatch.setattr(daemon, "PIDFILE", daemons_dir / "spotify.pid")
    monkeypatch.setattr(daemon, "LOG", tmp_path / "logs" / "spotify.log")
    monkeypatch.setattr(daemon, "SETTLE_SECS", 0)
    return daemons_dir


def _fake_popen(monkeypatch, launched, poll_result=None):
    def popen(argv, **kwargs):
        launched.append((argv, kwargs))
        return types.SimpleNamespace(pid=4321, poll=lambda: poll_result)

    monkeypatch.setattr(daemon.subprocess, "Popen", popen)


def test_start_is_a_no_op_while_the_recorded_process_is_alive(records, monkeypatch, capsys):
    daemon.PIDFILE.write_text(str(os.getpid()))
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("should not launch a duplicate daemon"))

    assert daemon.daemon_cmd("start") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already_running"}


def test_start_launches_the_organize_watcher_detached_and_records_its_pid(records, monkeypatch, capsys):
    launched = []
    _fake_popen(monkeypatch, launched)

    assert daemon.daemon_cmd("start") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "started"}
    argv, kwargs = launched[0]
    assert argv[1:] == ["organize", "watch"]
    assert kwargs["start_new_session"] is True
    # The record is "<pid> <starttime>": the pid is its first field, and whether the second one is
    # there at all depends on the fake pid happening to exist on this machine.
    assert daemon.PIDFILE.read_text().split()[0] == "4321"


def test_the_watcher_registers_no_vestad_port(records, monkeypatch):
    monkeypatch.setattr(daemon.subprocess, "run", lambda *a, **k: pytest.fail("the watcher serves nothing, so it registers nothing"))
    _fake_popen(monkeypatch, [])

    assert daemon.daemon_cmd("start") == 0
    assert list(records.glob("*.port")) == []


def test_status_reports_a_null_port_even_while_the_watcher_runs(records, capsys):
    daemon.PIDFILE.write_text(str(os.getpid()))

    assert daemon.daemon_cmd("status") == 0
    assert json.loads(capsys.readouterr().out) == {"running": True, "port": None}


def test_start_clears_its_record_when_the_watcher_exits_during_startup(records, monkeypatch, capsys):
    _fake_popen(monkeypatch, [], poll_result=1)

    assert daemon.daemon_cmd("start") == 1
    assert "exited during startup" in json.loads(capsys.readouterr().err)["error"]
    assert not daemon.PIDFILE.exists()


def test_a_start_that_loses_the_pid_claim_does_not_stack_a_second_watcher(records, monkeypatch, capsys):
    daemon.PIDFILE.write_text("4321")
    # None on the way in, then the rival start's daemon standing behind the record it claimed.
    monkeypatch.setattr(daemon, "live_pid", iter([None, 4321]).__next__)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("should not launch beside the claim winner"))

    assert daemon.daemon_cmd("start") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already_running"}


def test_stop_is_idempotent_when_nothing_is_recorded(records, capsys):
    assert daemon.daemon_cmd("stop") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already_stopped"}


def test_stop_sends_a_sigterm_and_clears_the_record(records, monkeypatch, capsys):
    daemon.PIDFILE.write_text("4321")
    signals = []
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    # alive for the signal, gone on the first poll after it
    monkeypatch.setattr(daemon, "live_pid", iter([4321, None]).__next__)

    assert daemon.daemon_cmd("stop") == 0
    assert signals == [(4321, signal.SIGTERM)]
    assert json.loads(capsys.readouterr().out) == {"status": "stopped"}
    assert not daemon.PIDFILE.exists()


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


def test_the_help_forms_succeed_and_an_unknown_verb_does_not(records, capsys):
    for action in ("", "-h", "--help", "help"):
        assert daemon.daemon_cmd(action) == 0
    assert "Usage" in capsys.readouterr().out
    assert daemon.daemon_cmd("bogus") == 1
    assert "Usage" in capsys.readouterr().err
