"""Black-box conformance harness for the skill daemon contract.

Drives each skill's real command as a subprocess in a hermetic HOME. The
contract: four verbs, JSON out, a pid and port record under ~/agent/data/daemons/,
a detached process, SIGTERM as the deliberate stop, and a status that reads those
records rather than vestad. One table row per skill.
"""

import contextlib
import dataclasses
import json
import os
import pathlib as pl
import signal
import socket
import subprocess
import typing as tp

import pytest

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "agent/skills"
# status is a local read of two files, so anything near a registration round trip is a regression.
STATUS_TIMEOUT = 10

FAKE_REGISTER_SERVICE = """#!/bin/sh
echo "$*" >> "$HOME/register-args"
cat "$HOME/fake-port"
"""


@dataclasses.dataclass(frozen=True)
class Daemon:
    command: list[str]  # argv prefix, e.g. [str(SKILLS_DIR / "file-host/file-host")]
    name: str  # pidfile name and log name
    serves_port: bool
    emits_daemon_died: bool
    service: str | None = None  # vestad service name, when it differs from the command name
    rig: tp.Callable[[pl.Path, pl.Path], None] | None = None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _rig_file_host(home: pl.Path, bin_dir: pl.Path) -> None:
    served = home / ".file-host"
    served.mkdir()
    (served / "hello.txt").write_text("hi")


def _rig_dashboard(home: pl.Path, bin_dir: pl.Path) -> None:
    """The app is served from build artifacts, so the skill's link is swapped for a tree
    holding both plus the real launch script, with a fake vite standing in for the server."""
    skill = home / "agent/skills/dashboard"
    skill.unlink()
    (skill / "app/dist").mkdir(parents=True)
    (skill / "scripts").mkdir()
    (skill / "scripts/serve").symlink_to(SKILLS_DIR / "dashboard/scripts/serve")
    vite = skill / "app/node_modules/.bin/vite"
    vite.parent.mkdir(parents=True)
    # `vite preview --port <port> --host 0.0.0.0`, so the port is the third argument.
    vite.write_text('#!/bin/sh\nexec python3 -m http.server "$3" --bind 0.0.0.0\n')
    vite.chmod(0o755)


SKILLS = [
    Daemon(
        command=[str(SKILLS_DIR / "file-host/file-host")],
        name="file-host",
        serves_port=True,
        emits_daemon_died=False,
        rig=_rig_file_host,
    ),
    Daemon(
        command=[str(SKILLS_DIR / "sign-service/sign-service")],
        name="sign-service",
        serves_port=True,
        emits_daemon_died=False,
        service="sign",
    ),
    Daemon(
        command=[str(SKILLS_DIR / "moneypot/moneypot")],
        name="moneypot",
        serves_port=True,
        emits_daemon_died=False,
    ),
    Daemon(
        command=[str(SKILLS_DIR / "dashboard/dashboard")],
        name="dashboard",
        serves_port=True,
        emits_daemon_died=False,
        rig=_rig_dashboard,
    ),
]


@pytest.fixture(params=SKILLS, ids=lambda d: d.name)
def daemon(request, tmp_path):
    spec: Daemon = request.param
    home = tmp_path / "home"
    (home / "agent/data/daemons").mkdir(parents=True)
    (home / "agent/logs").mkdir(parents=True)
    # A box's HOME is the checkout, so every launcher reaches its own files through
    # $HOME/agent/skills. One link per skill gives the hermetic HOME that same layout while
    # leaving a rig free to swap a single skill for a writable stand-in.
    skills = home / "agent/skills"
    skills.mkdir()
    for skill in SKILLS_DIR.iterdir():
        (skills / skill.name).symlink_to(skill)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    reg = bin_dir / "register-service"
    reg.write_text(FAKE_REGISTER_SERVICE)
    reg.chmod(0o755)
    (home / "fake-port").write_text(str(_free_port()))
    if spec.rig:
        spec.rig(home, bin_dir)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    yield spec, home, env
    # Always tear down: a leaked daemon poisons later tests.
    pidfile = home / "agent/data/daemons" / f"{spec.name}.pid"
    if pidfile.exists():
        with contextlib.suppress(ProcessLookupError, ValueError):
            os.kill(int(pidfile.read_text()), signal.SIGKILL)


def _verb(spec, env, *args):
    return subprocess.run([*spec.command, "daemon", *args], env=env, capture_output=True, text=True, check=False, timeout=60)


def _pid(spec, home) -> int | None:
    pidfile = home / "agent/data/daemons" / f"{spec.name}.pid"
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 0)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return None
    return pid


def test_start_is_idempotent_and_never_stacks(daemon):
    spec, home, env = daemon
    first = _verb(spec, env, "start")
    assert first.returncode == 0, first.stdout + first.stderr
    assert json.loads(first.stdout) == {"status": "started"}
    pid = _pid(spec, home)
    assert pid is not None
    second = _verb(spec, env, "start")
    assert json.loads(second.stdout) == {"status": "already_running"}
    assert _pid(spec, home) == pid


def test_start_fails_closed_when_registration_fails(daemon):
    spec, home, env = daemon
    if not spec.serves_port:
        pytest.skip("portless")
    (pl.Path(env["PATH"].split(":")[0]) / "register-service").write_text("#!/bin/sh\nexit 1\n")
    result = _verb(spec, env, "start")
    assert result.returncode != 0
    error = json.loads(result.stderr)["error"]
    assert isinstance(error, str) and error
    assert not (home / "agent/data/daemons" / f"{spec.name}.pid").exists()


def test_stop_kills_the_process_and_status_tells_the_truth(daemon):
    spec, home, env = daemon
    _verb(spec, env, "start")
    running = json.loads(_verb(spec, env, "status").stdout)
    assert running["running"] is True
    pid = _pid(spec, home)
    assert pid is not None
    stopped = _verb(spec, env, "stop")
    assert json.loads(stopped.stdout) == {"status": "stopped"}
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert json.loads(_verb(spec, env, "status").stdout)["running"] is False
    assert json.loads(_verb(spec, env, "stop").stdout) == {"status": "already_stopped"}


def test_restart_replaces_a_running_daemon_and_starts_a_stopped_one(daemon):
    """The verb a restart file calls, so it has to land on a live daemon either way."""
    spec, home, env = daemon
    assert json.loads(_verb(spec, env, "start").stdout) == {"status": "started"}
    before = _pid(spec, home)
    assert before is not None
    restarted = _verb(spec, env, "restart")
    assert json.loads(restarted.stdout) == {"status": "started"}, restarted.stdout + restarted.stderr
    after = _pid(spec, home)
    assert after is not None
    assert after != before
    with pytest.raises(ProcessLookupError):
        os.kill(before, 0)
    assert json.loads(_verb(spec, env, "status").stdout)["running"] is True

    assert json.loads(_verb(spec, env, "stop").stdout) == {"status": "stopped"}
    from_stopped = _verb(spec, env, "restart")
    assert json.loads(from_stopped.stdout) == {"status": "started"}, from_stopped.stdout + from_stopped.stderr
    assert _pid(spec, home) is not None
    assert json.loads(_verb(spec, env, "status").stdout)["running"] is True
    _verb(spec, env, "stop")


def test_deliberate_stop_is_not_reported_as_a_crash(daemon):
    spec, home, env = daemon
    if not spec.emits_daemon_died:
        pytest.skip("does not self-report death")
    assert json.loads(_verb(spec, env, "start").stdout) == {"status": "started"}
    assert json.loads(_verb(spec, env, "stop").stdout) == {"status": "stopped"}
    notif_dir = home / "agent/notifications"
    died = list(notif_dir.glob("*daemon_died*")) if notif_dir.exists() else []
    assert died == []


def test_status_reads_the_port_record_and_never_re_registers(daemon):
    """A daemon outlives vestad restarts, so status answers from what start recorded."""
    spec, home, env = daemon
    if not spec.serves_port:
        pytest.skip("portless")
    assert json.loads(_verb(spec, env, "start").stdout) == {"status": "started"}
    (pl.Path(env["PATH"].split(":")[0]) / "register-service").unlink()
    result = subprocess.run([*spec.command, "daemon", "status"], env=env, capture_output=True, text=True, check=False, timeout=STATUS_TIMEOUT)
    assert json.loads(result.stdout) == {"running": True, "port": int((home / "fake-port").read_text())}
    _verb(spec, env, "stop")


def test_registration_declares_the_expected_exposure(daemon):
    spec, home, env = daemon
    if not spec.serves_port:
        pytest.skip("portless")
    _verb(spec, env, "start")
    args = (home / "register-args").read_text().strip()
    public = {"file-host", "agentmail"}
    service = spec.service or spec.name
    expected = f"{service} --public" if service in public else service
    assert args.splitlines()[0] == expected
    _verb(spec, env, "stop")


def test_usage_and_unknown_verbs(daemon):
    spec, _home, env = daemon
    for args in ([], ["-h"], ["--help"]):
        result = subprocess.run([*spec.command, *args], env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 0
        assert "Usage" in result.stdout
    assert _verb(spec, env, "bogus").returncode != 0
