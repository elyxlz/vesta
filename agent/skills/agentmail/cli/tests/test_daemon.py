"""The agentmail daemon owns the four verbs itself: it registers its port with vestad, records it
beside the pid, holds the start open until the bridge answers, and stops with a SIGTERM the serve
path reads as deliberate. The bridge registers public because AgentMail's webhook reaches it from
outside the tunnel with no credential, and /health is what readiness is probed on."""

import json
import os
import signal
import types

import pytest
from agentmail_bridge import daemon


@pytest.fixture
def records(tmp_path, monkeypatch):
    """Redirects the pid and port records into a tmpdir, the way a hermetic HOME would."""
    daemons_dir = tmp_path / "daemons"
    daemons_dir.mkdir()
    monkeypatch.setattr(daemon, "DAEMONS_DIR", daemons_dir)
    monkeypatch.setattr(daemon, "PIDFILE", daemons_dir / "agentmail.pid")
    monkeypatch.setattr(daemon, "PORTFILE", daemons_dir / "agentmail.port")
    monkeypatch.setattr(daemon, "LOG", tmp_path / "logs" / "agentmail.log")
    return daemons_dir


def _record_runs(monkeypatch, seen, returncode=0, stdout=""):
    def run(argv, **kwargs):
        seen.append(argv)
        return types.SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(daemon.subprocess, "run", run)


def test_registration_asks_vestad_for_a_public_port(monkeypatch):
    seen = []
    _record_runs(monkeypatch, seen, stdout="5150\n")

    assert daemon._register_port() == "5150"
    assert seen == [["register-service", "agentmail", "--public"]]


def test_registration_is_refused_when_vestad_hands_out_no_port(monkeypatch):
    _record_runs(monkeypatch, [], returncode=1, stdout="")

    assert daemon._register_port() is None


def test_the_readiness_probe_curls_the_health_path(monkeypatch):
    seen = []
    _record_runs(monkeypatch, seen)

    assert daemon._ready("5150") is True
    assert seen[0][-1] == "http://localhost:5150/health"


def test_start_is_a_no_op_while_the_recorded_process_is_alive(records, monkeypatch, capsys):
    daemon.PIDFILE.write_text(str(os.getpid()))
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("should not launch a duplicate daemon"))

    assert daemon.daemon_action("start") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already_running"}


def test_start_fails_closed_when_registration_fails(records, monkeypatch, capsys):
    monkeypatch.setattr(daemon, "_register_port", lambda: None)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch without a port"))

    assert daemon.daemon_action("start") == 1
    assert "register" in json.loads(capsys.readouterr().err)["error"]
    assert not daemon.PIDFILE.exists()


def test_start_records_the_pid_and_port_of_a_bridge_that_answers(records, monkeypatch, capsys):
    launched = []

    def fake_popen(argv, **kwargs):
        launched.append((argv, kwargs))
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(daemon, "_register_port", lambda: "5150")
    monkeypatch.setattr(daemon, "_ready", lambda port: True)
    monkeypatch.setattr(daemon.subprocess, "Popen", fake_popen)

    assert daemon.daemon_action("start") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "started"}
    argv, kwargs = launched[0]
    assert argv[1:] == ["serve", "--port", "5150"]
    assert kwargs["start_new_session"] is True
    assert daemon.PIDFILE.read_text() == "4321"
    assert daemon.PORTFILE.read_text() == "5150"


def test_a_start_that_never_gets_an_answer_takes_its_child_and_both_records_with_it(records, monkeypatch, capsys):
    terminated = []
    child = types.SimpleNamespace(pid=4321, poll=lambda: None, terminate=lambda: terminated.append(True), wait=lambda timeout=None: None)
    monkeypatch.setattr(daemon, "_register_port", lambda: "5150")
    monkeypatch.setattr(daemon, "_ready", lambda port: False)
    monkeypatch.setattr(daemon, "READY_TIMEOUT_SECS", 0)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: child)

    assert daemon.daemon_action("start") == 1
    assert "never answered" in json.loads(capsys.readouterr().err)["error"]
    assert terminated == [True]
    assert not daemon.PIDFILE.exists()
    assert not daemon.PORTFILE.exists()


def test_stop_is_idempotent_when_nothing_is_recorded(records, capsys):
    assert daemon.daemon_action("stop") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already_stopped"}


def test_stop_sends_a_sigterm_and_clears_both_records(records, monkeypatch, capsys):
    daemon.PIDFILE.write_text("4321")
    daemon.PORTFILE.write_text("5150")
    signals = []
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    # alive for the signal, gone on the first poll after it
    monkeypatch.setattr(daemon, "live_pid", iter([4321, None]).__next__)

    assert daemon.daemon_action("stop") == 0
    assert signals == [(4321, signal.SIGTERM)]
    assert json.loads(capsys.readouterr().out) == {"status": "stopped"}
    assert not daemon.PIDFILE.exists()
    assert not daemon.PORTFILE.exists()


def test_restart_prints_one_line_and_skips_the_start_when_the_stop_fails(records, monkeypatch, capsys):
    daemon.PIDFILE.write_text(str(os.getpid()))
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(daemon, "STOP_TIMEOUT_SECS", 0)
    monkeypatch.setattr(daemon, "_start", lambda: pytest.fail("must not start onto a daemon that is still there"))

    assert daemon.daemon_action("restart") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SIGTERM" in json.loads(captured.err)["error"]


def test_status_reads_the_records_rather_than_vestad(records, monkeypatch, capsys):
    monkeypatch.setattr(daemon.subprocess, "run", lambda *a, **k: pytest.fail("status is a local read of two files"))
    assert daemon.daemon_action("status") == 0
    assert json.loads(capsys.readouterr().out) == {"running": False, "port": None}

    daemon.PIDFILE.write_text(str(os.getpid()))
    daemon.PORTFILE.write_text("5150")

    assert daemon.daemon_action("status") == 0
    assert json.loads(capsys.readouterr().out) == {"running": True, "port": 5150}


def test_the_help_forms_succeed_and_an_unknown_verb_does_not(records, capsys):
    for action in ("", "-h", "--help", "help"):
        assert daemon.daemon_action(action) == 0
    assert "Usage" in capsys.readouterr().out
    assert daemon.daemon_action("bogus") == 1
    assert "Usage" in capsys.readouterr().err
