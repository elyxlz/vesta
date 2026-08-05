"""The poll daemon's lifecycle, driven in process, plus the account auth listing.

Four verbs over one pid record: a start claims the record before it spawns anything, a start
that finds a live daemon answers already_running, stop is the SIGTERM that ends it, restart
does not start onto a daemon the stop could not kill, and status answers from the record
alone. agent/tests/test_daemon_contract.py drives the same verbs as real subprocesses; this
suite covers the decisions behind them.

The imap module imports imap_tools, so a minimal stub is registered first.
"""

import dataclasses
import importlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
import types

import pytest
from email_client import daemon as dl
from email_client import poll_daemon

# The default the module falls back to when the environment names no stop budget.
DEFAULT_STOP_TIMEOUT_SECS = 15
CHILD_PID = 424242
# A live child either dies on the first SIGTERM or is a bug, so these bound a test, not a wait.
CHILD_TIMEOUT_SECS = 10
READY_TIMEOUT_SECS = 10
READY_POLL_SECS = 0.01
STUCK_STOP_BUDGET_SECS = 1
# Installs the handler, then says so: a SIGTERM sent before that line would kill it.
DEAF_TO_SIGTERM = (
    "import pathlib, signal, sys, time; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "pathlib.Path(sys.argv[1]).write_text('ready'); "
    "time.sleep(30)"
)


def _install_imap_tools_stub():
    if "imap_tools" not in sys.modules:
        it = types.ModuleType("imap_tools")

        def _and(*_a, **_k):
            return None

        class MailBox:
            def __init__(self, *_a, **_k):
                pass

        class MailMessageFlags:
            DRAFT = "\\Draft"
            SEEN = "\\Seen"
            ANSWERED = "\\Answered"
            FLAGGED = "\\Flagged"

        class MailboxUidsError(Exception):
            pass

        it.AND = _and
        it.MailBox = MailBox
        it.MailMessageFlags = MailMessageFlags
        it.MailboxUidsError = MailboxUidsError
        sys.modules["imap_tools"] = it


_install_imap_tools_stub()
from email_client import imap as imap_client


@dataclasses.dataclass(frozen=True)
class _Spawned:
    argv: list[str]
    detached: bool
    log_path: str
    record: str


@pytest.fixture
def records(tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
    """Point the module's records and log at a tmp home, and shrink the two waits that would
    otherwise only make the suite slower."""
    daemons = tmp_path / "agent/data/daemons"
    daemons.mkdir(parents=True)
    monkeypatch.setattr(dl, "DAEMONS_DIR", daemons)
    monkeypatch.setattr(dl, "PIDFILE", daemons / f"{dl.NAME}.pid")
    monkeypatch.setattr(dl, "LOG", tmp_path / "agent/logs" / f"{dl.NAME}.log")
    monkeypatch.setattr(dl, "SETTLE_SECS", 0)
    monkeypatch.setattr(dl, "POLL_SECS", READY_POLL_SECS)
    return tmp_path


@pytest.fixture
def deaf_daemon(records: pathlib.Path, monkeypatch):
    """A live process that ignores SIGTERM: the daemon a stop has to escalate on."""
    marker = records / "deaf-ready"
    child = subprocess.Popen([sys.executable, "-c", DEAF_TO_SIGTERM, str(marker)])
    _wait_until(marker.exists, "the child never installed its SIGTERM handler")
    monkeypatch.setattr(dl, "STOP_TIMEOUT_SECS", STUCK_STOP_BUDGET_SECS)
    dl.PIDFILE.write_text(str(child.pid))
    yield child
    child.kill()
    child.wait(timeout=CHILD_TIMEOUT_SECS)


@pytest.fixture
def unstoppable_daemon(records: pathlib.Path, monkeypatch):
    """A daemon no signal reaches, which is the only state a stop has to give up on now that it
    escalates: SIGKILL ends any process the box can signal at all. Swallowing the signals is what
    models it, and it also leaves live_pid reporting the recorded pid alive throughout."""
    monkeypatch.setattr(dl.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(dl, "STOP_TIMEOUT_SECS", STUCK_STOP_BUDGET_SECS)
    dl.PIDFILE.write_text(str(os.getpid()))
    return os.getpid()


def _wait_until(condition, message: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(READY_POLL_SECS)
    raise AssertionError(message)


def _capture_spawn(monkeypatch, *, exit_code: int | None = None) -> list[_Spawned]:
    spawns: list[_Spawned] = []

    class _Child:
        pid = CHILD_PID

        def poll(self) -> int | None:
            return exit_code

    def fake_popen(argv, *, start_new_session, stdout, stderr):
        spawns.append(
            _Spawned(
                argv=list(argv),
                detached=start_new_session,
                log_path=stdout.name,
                record=dl.PIDFILE.read_text(),
            )
        )
        return _Child()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return spawns


def _refuse_spawn(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("nothing may be spawned beside a daemon that is already up")

    monkeypatch.setattr(subprocess, "Popen", fail)


def test_status_reports_stopped_when_no_record_exists(records: pathlib.Path, capsys):
    assert dl.daemon_cmd("status") == 0

    assert json.loads(capsys.readouterr().out) == {"running": False, "port": None}


def test_status_reads_the_record_and_reports_no_port(records: pathlib.Path, capsys):
    dl.PIDFILE.write_text(str(os.getpid()))

    assert dl.daemon_cmd("status") == 0

    # The poller dials out and writes notification files, so it serves nothing to report.
    assert json.loads(capsys.readouterr().out) == {"running": True, "port": None}


@pytest.mark.parametrize("record", [str(2**30), "not-a-pid", ""])
def test_status_reports_stopped_when_no_process_stands_behind_the_record(records: pathlib.Path, capsys, record: str):
    dl.PIDFILE.write_text(record)

    assert dl.daemon_cmd("status") == 0

    assert json.loads(capsys.readouterr().out) == {"running": False, "port": None}


def test_start_claims_the_record_before_it_spawns_anything(records: pathlib.Path, monkeypatch, capsys):
    spawns = _capture_spawn(monkeypatch)

    assert dl.daemon_cmd("start") == 0

    assert json.loads(capsys.readouterr().out) == {"status": "started"}
    assert [spawn.record for spawn in spawns] == [str(os.getpid())]
    assert dl.PIDFILE.read_text() == str(CHILD_PID)


def test_start_runs_the_poller_detached_and_names_no_cadence(records: pathlib.Path, monkeypatch, capsys):
    spawns = _capture_spawn(monkeypatch)

    dl.daemon_cmd("start")

    capsys.readouterr()
    # start re-invokes the same console entry with the internal `poll` subcommand; no cadence
    # flag, so the poller reads its interval from the environment.
    assert [spawn.argv for spawn in spawns] == [[sys.argv[0], "poll"]]
    assert [spawn.detached for spawn in spawns] == [True]
    assert [spawn.log_path for spawn in spawns] == [str(dl.LOG)]


def test_start_answers_already_running_and_never_stacks(records: pathlib.Path, monkeypatch, capsys):
    dl.PIDFILE.write_text(str(os.getpid()))
    _refuse_spawn(monkeypatch)

    assert dl.daemon_cmd("start") == 0

    assert json.loads(capsys.readouterr().out) == {"status": "already_running"}
    assert dl.PIDFILE.read_text() == str(os.getpid())


def test_start_that_loses_the_claim_answers_already_running(records: pathlib.Path, monkeypatch, capsys):
    """A rival start holds the record and its daemon comes up during the wait, so this start
    reports the rival's daemon instead of spawning a second one beside it."""
    rival_pid = 4242
    dl.PIDFILE.write_text("")
    _refuse_spawn(monkeypatch)
    liveness = iter([None])
    monkeypatch.setattr(dl, "live_pid", lambda: next(liveness, rival_pid))

    assert dl.daemon_cmd("start") == 0

    assert json.loads(capsys.readouterr().out) == {"status": "already_running"}
    assert dl.PIDFILE.read_text() == ""


def test_start_takes_over_a_record_no_process_stands_behind(records: pathlib.Path, monkeypatch, capsys):
    dl.PIDFILE.write_text(str(2**30))
    monkeypatch.setattr(dl, "CLAIM_WAIT_SECS", 0)
    spawns = _capture_spawn(monkeypatch)

    assert dl.daemon_cmd("start") == 0

    assert json.loads(capsys.readouterr().out) == {"status": "started"}
    assert len(spawns) == 1
    assert dl.PIDFILE.read_text() == str(CHILD_PID)


def test_start_that_gives_up_removes_its_own_record(records: pathlib.Path, monkeypatch, capsys):
    _capture_spawn(monkeypatch, exit_code=1)

    assert dl.daemon_cmd("start") == 1

    # A record that says a dead daemon is up turns every later start into a no-op.
    assert dl.PIDFILE.exists() is False
    error = json.loads(capsys.readouterr().err)["error"]
    assert dl.NAME in error
    assert str(dl.LOG) in error


def test_stop_answers_already_stopped_when_nothing_is_running(records: pathlib.Path, capsys):
    assert dl.daemon_cmd("stop") == 0

    assert json.loads(capsys.readouterr().out) == {"status": "already_stopped"}


def test_stop_sigterms_the_daemon_and_clears_the_record(records: pathlib.Path, capsys):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    answers: list[int] = []
    try:
        dl.PIDFILE.write_text(str(child.pid))
        # live_pid asks os.kill(pid, 0), which reports this process's own terminated child as
        # alive until it is reaped, so the stop runs beside the wait that reaps it.
        stopper = threading.Thread(target=lambda: answers.append(dl.daemon_cmd("stop")))
        stopper.start()
        assert child.wait(timeout=CHILD_TIMEOUT_SECS) == -signal.SIGTERM
        stopper.join(timeout=CHILD_TIMEOUT_SECS)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=CHILD_TIMEOUT_SECS)

    assert answers == [0]
    assert json.loads(capsys.readouterr().out) == {"status": "stopped"}
    assert dl.PIDFILE.exists() is False


def test_stop_kills_a_daemon_that_ignores_sigterm(records: pathlib.Path, deaf_daemon, capsys):
    """SIGTERM is the exit the agent asked for, but a daemon that ignores it is killed rather than
    left standing behind records that say it is up."""
    answers: list[int] = []
    stopper = threading.Thread(target=lambda: answers.append(dl.daemon_cmd("stop")))
    stopper.start()
    # live_pid asks os.kill(pid, 0), which reports this process's own killed child as alive until
    # it is reaped, so the stop runs beside the wait that reaps it.
    assert deaf_daemon.wait(timeout=CHILD_TIMEOUT_SECS) == -signal.SIGKILL
    stopper.join(timeout=CHILD_TIMEOUT_SECS)

    assert answers == [0]
    assert json.loads(capsys.readouterr().out) == {"status": "stopped"}
    assert dl.PIDFILE.exists() is False


def test_stop_gives_up_when_the_daemon_outlives_the_budget(records: pathlib.Path, unstoppable_daemon, capsys):
    assert dl.daemon_cmd("stop") == 1

    error = json.loads(capsys.readouterr().err)["error"]
    assert "still running" in error
    assert str(unstoppable_daemon) in error
    # Neither signal reached it, so the daemon is still there and the record still names it.
    assert dl.PIDFILE.read_text() == str(unstoppable_daemon)


def test_the_stop_budget_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("DAEMON_STOP_TIMEOUT_SECS", "42")
    assert importlib.reload(dl).STOP_TIMEOUT_SECS == 42

    monkeypatch.delenv("DAEMON_STOP_TIMEOUT_SECS")
    assert importlib.reload(dl).STOP_TIMEOUT_SECS == DEFAULT_STOP_TIMEOUT_SECS


def test_restart_starts_a_stopped_daemon_and_answers_once(records: pathlib.Path, monkeypatch, capsys):
    spawns = _capture_spawn(monkeypatch)

    assert dl.daemon_cmd("restart") == 0

    # One verb, one answer: the stop half is swallowed.
    assert capsys.readouterr().out == json.dumps({"status": "started"}) + "\n"
    assert len(spawns) == 1


def test_restart_does_not_start_when_the_stop_failed(records: pathlib.Path, unstoppable_daemon, monkeypatch, capsys):
    _refuse_spawn(monkeypatch)

    assert dl.daemon_cmd("restart") == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "still running" in json.loads(captured.err)["error"]


def test_the_poll_cadence_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("EMAIL_CLIENT_POLL_INTERVAL", "7")
    assert poll_daemon._interval_default() == 7

    monkeypatch.delenv("EMAIL_CLIENT_POLL_INTERVAL")
    assert poll_daemon._interval_default() == poll_daemon.DEFAULT_POLL_INTERVAL_SECS


def test_a_death_notification_names_the_skill_and_the_reason(tmp_path: pathlib.Path, monkeypatch):
    notifications = tmp_path / "notifications"
    monkeypatch.setattr(poll_daemon, "NOTIF_DIR", notifications)

    poll_daemon.write_daemon_died_notification("SIGINT")

    written = [json.loads(path.read_text()) for path in notifications.iterdir() if path.suffix == ".json"]
    assert written == [
        {
            "source": dl.NAME,
            "type": "daemon_died",
            "reason": "SIGINT",
            "timestamp": written[0]["timestamp"],
        }
    ]
    # The file lands complete or not at all, so the agent never reads a half-written one.
    assert [path.name for path in notifications.iterdir() if path.suffix == ".tmp"] == []


@pytest.mark.parametrize(
    "cfg,tok,expected",
    [
        (
            {"user": "a@example.com", "provider": "gmail"},
            None,
            {"account": "personal", "user": "a@example.com", "provider": "gmail", "default": True, "has_token": False},
        ),
        (
            {"user": "a@example.com", "provider": "generic"},
            {"app_password": "secret"},
            {"account": "personal", "user": "a@example.com", "provider": "generic", "default": True, "has_token": True},
        ),
        (
            {"user": "a@example.com", "provider": "gmail"},
            {"refresh_token": "rt"},
            {"account": "personal", "user": "a@example.com", "provider": "gmail", "default": True, "has_token": True},
        ),
        (
            {},
            {"user": "token-user@example.com", "provider": "microsoft-personal"},
            {
                "account": "personal",
                "user": "token-user@example.com",
                "provider": "microsoft-personal",
                "default": True,
                "has_token": True,
            },
        ),
    ],
)
def test_auth_list_reports_each_account_and_whether_it_holds_a_token(tmp_path: pathlib.Path, monkeypatch, capsys, cfg, tok, expected):
    monkeypatch.setenv("EMAIL_CLIENT_DIR", str(tmp_path / "email-client"))
    imap_client.save_accounts_index({"accounts": ["personal"], "default": "personal"})
    imap_client.save_config("personal", cfg)
    if tok is not None:
        imap_client.save_token("personal", tok)

    imap_client.cmd_auth_list(None)

    # Public metadata only: no secret from the token file reaches the listing.
    assert json.loads(capsys.readouterr().out) == [expected]
