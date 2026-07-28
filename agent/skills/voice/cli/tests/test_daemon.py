"""The voice daemon owns the four verbs itself: it registers a private port with vestad, hands it
to the server through the environment, holds the start open until /health answers, and stops with a
SIGTERM the server reads as deliberate. Provider auth is reported by `voice-keys status`, which
reads the same voice config the server does.
"""

import json
import os
import pathlib as pl
import signal
import types

import pytest
import voice.config as vc
from voice import daemon, voice_keys


@pytest.fixture
def records(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> pl.Path:
    """Redirects the pid and port records into a tmpdir, the way a hermetic HOME would."""
    daemons_dir = tmp_path / "daemons"
    daemons_dir.mkdir()
    monkeypatch.setattr(daemon, "DAEMONS_DIR", daemons_dir)
    monkeypatch.setattr(daemon, "PIDFILE", daemons_dir / "voice.pid")
    monkeypatch.setattr(daemon, "PORTFILE", daemons_dir / "voice.port")
    monkeypatch.setattr(daemon, "LOG", tmp_path / "logs" / "voice.log")
    monkeypatch.setattr(daemon.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    return daemons_dir


def _record_runs(monkeypatch: pytest.MonkeyPatch, seen: list[list[str]], returncode: int = 0, stdout: str = "") -> None:
    def run(argv, **kwargs):
        seen.append(argv)
        return types.SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(daemon.subprocess, "run", run)


def test_status_reports_no_providers_while_voice_is_unconfigured(
    tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(voice_keys, "_data_dir", lambda: tmp_path)

    assert voice_keys.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out) == {"stt": None, "tts": None}


def test_status_reports_the_provider_and_enabled_flag_of_each_domain(
    tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(voice_keys, "_data_dir", lambda: tmp_path)
    vc.set_key(tmp_path, "stt", "deepgram", "k")
    vc.set_enabled(tmp_path, "tts", True)
    vc.set_key(tmp_path, "tts", "elevenlabs", "k2")

    assert voice_keys.main(["status"]) == 0
    reported = json.loads(capsys.readouterr().out)
    assert reported["stt"]["provider"] == "deepgram"
    assert reported["stt"]["enabled"] is True
    assert reported["tts"]["provider"] == "elevenlabs"
    assert reported["tts"]["enabled"] is True


def test_registration_asks_vestad_for_a_private_port(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    _record_runs(monkeypatch, seen, stdout="5150\n")

    assert daemon._register_port() == "5150"
    assert seen == [["register-service", "voice"]]


def test_registration_is_refused_when_vestad_hands_out_no_port(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_runs(monkeypatch, [], returncode=1, stdout="")

    assert daemon._register_port() is None


def test_the_readiness_probe_curls_the_health_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    _record_runs(monkeypatch, seen)

    assert daemon._ready("5150") is True
    assert seen[0][-1] == "http://localhost:5150/health"


def test_start_refuses_and_claims_nothing_without_the_server_on_path(
    records: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(daemon.shutil, "which", lambda name: None)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch a server that is not installed"))

    assert daemon.daemon_cmd("start") == 1
    assert "voice-server" in json.loads(capsys.readouterr().err)["error"]
    assert not daemon.PIDFILE.exists()


def test_start_is_a_no_op_while_the_recorded_process_is_alive(
    records: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    daemon.PIDFILE.write_text(str(os.getpid()))
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("should not launch a duplicate daemon"))

    assert daemon.daemon_cmd("start") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already_running"}


def test_start_fails_closed_when_registration_fails(
    records: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(daemon, "_register_port", lambda: None)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch without a port"))

    assert daemon.daemon_cmd("start") == 1
    assert "register" in json.loads(capsys.readouterr().err)["error"]
    assert not daemon.PIDFILE.exists()


def test_start_hands_the_registered_port_to_the_server_through_the_environment(
    records: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    launched = []

    def fake_popen(argv, **kwargs):
        launched.append((argv, kwargs))
        return types.SimpleNamespace(pid=4321, poll=lambda: None)

    monkeypatch.setattr(daemon, "_register_port", lambda: "5150")
    monkeypatch.setattr(daemon, "_ready", lambda port: True)
    monkeypatch.setattr(daemon.subprocess, "Popen", fake_popen)

    assert daemon.daemon_cmd("start") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "started"}
    argv, kwargs = launched[0]
    assert argv == ["/usr/local/bin/voice-server"]
    assert kwargs["env"]["SKILL_PORT"] == "5150"
    assert kwargs["start_new_session"] is True
    assert daemon.PIDFILE.read_text() == "4321"
    assert daemon.PORTFILE.read_text() == "5150"


def test_a_start_that_never_gets_an_answer_takes_its_child_and_both_records_with_it(
    records: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    terminated = []
    child = types.SimpleNamespace(pid=4321, poll=lambda: None, terminate=lambda: terminated.append(True), wait=lambda timeout=None: None)
    monkeypatch.setattr(daemon, "_register_port", lambda: "5150")
    monkeypatch.setattr(daemon, "_ready", lambda port: False)
    monkeypatch.setattr(daemon, "READY_TIMEOUT_SECS", 0)
    monkeypatch.setattr(daemon.subprocess, "Popen", lambda *a, **k: child)

    assert daemon.daemon_cmd("start") == 1
    assert "never answered" in json.loads(capsys.readouterr().err)["error"]
    assert terminated == [True]
    assert not daemon.PIDFILE.exists()
    assert not daemon.PORTFILE.exists()


def test_stop_is_idempotent_when_nothing_is_recorded(records: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert daemon.daemon_cmd("stop") == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already_stopped"}


def test_stop_sends_a_sigterm_and_clears_both_records(
    records: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
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


def test_restart_prints_one_line_and_skips_the_start_when_the_stop_fails(
    records: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    daemon.PIDFILE.write_text(str(os.getpid()))
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(daemon, "STOP_TIMEOUT_SECS", 0)
    monkeypatch.setattr(daemon, "_start", lambda: pytest.fail("must not start onto a daemon that is still there"))

    assert daemon.daemon_cmd("restart") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SIGTERM" in json.loads(captured.err)["error"]


def test_status_reads_the_records_rather_than_vestad(
    records: pl.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(daemon.subprocess, "run", lambda *a, **k: pytest.fail("status is a local read of two files"))
    assert daemon.daemon_cmd("status") == 0
    assert json.loads(capsys.readouterr().out) == {"running": False, "port": None}

    daemon.PIDFILE.write_text(str(os.getpid()))
    daemon.PORTFILE.write_text("5150")

    assert daemon.daemon_cmd("status") == 0
    assert json.loads(capsys.readouterr().out) == {"running": True, "port": 5150}


def test_a_record_no_process_stands_behind_reads_as_stopped(records: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    daemon.PIDFILE.write_text("2147483646")
    daemon.PORTFILE.write_text("5150")

    assert daemon.daemon_cmd("status") == 0
    assert json.loads(capsys.readouterr().out) == {"running": False, "port": None}


def test_the_help_forms_succeed_and_an_unknown_verb_does_not(records: pl.Path, capsys: pytest.CaptureFixture[str]) -> None:
    for action in ("", "-h", "--help", "help"):
        assert daemon.daemon_cmd(action) == 0
    assert "Usage" in capsys.readouterr().out
    assert daemon.daemon_cmd("bogus") == 1
    assert "Usage" in capsys.readouterr().err
