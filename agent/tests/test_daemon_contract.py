"""Black-box conformance harness for the skill daemon contract.

Drives each skill's real command as a subprocess in a hermetic HOME. The
contract: four verbs, JSON out, a pid and port record under ~/agent/data/daemons/,
a detached process, SIGTERM as the deliberate stop, and a status that reads those
records rather than vestad. One table row per skill.
"""

import contextlib
import dataclasses
import hashlib
import json
import os
import pathlib as pl
import shutil
import signal
import socket
import subprocess
import time
import typing as tp

import pytest

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "agent/skills"
# status is a local read of two files, so anything near a registration round trip is a regression.
STATUS_TIMEOUT = 10
DEATH_REPORT_TIMEOUT = 30
DEATH_POLL_SECS = 0.2
# Short enough that a start which gives up is a test rather than a wait.
UNREADY_TIMEOUT_SECS = "2"
PID_CAPTURE_POLL_SECS = 0.02
# Two starts, launched with no stagger: whoever wins the record is the one that spawns.
RACE_STARTS = 2
RACE_TIMEOUT = 120
# The whatsapp launcher answers --help off its cached binary, so this only has to outlast a cold
# disk; the one path that would compile first is the one this probe is never taken on.
WHATSAPP_PROBE_TIMEOUT = 120

# Every registration hands out a port that is free right now, as vestad does. A constant one
# reused across a test's starts races the kernel: the port a stopped daemon just released can be
# taken by anything before the next start binds it.
FAKE_REGISTER_SERVICE = """#!/bin/sh
echo "$*" >> "$HOME/register-args"
exec python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
"""

# Sends every readiness probe, flags and all, to a listener that accepts and then says nothing.
# The daemon still comes up on its own port, so this is a daemon that is alive and unreachable.
MUTE_CURL = """#!/bin/sh
for arg do
  shift
  case "$arg" in
    http://*) set -- "$@" "http://127.0.0.1:$MUTE_PORT/" ;;
    *) set -- "$@" "$arg" ;;
  esac
done
exec {curl} "$@"
"""


@dataclasses.dataclass(frozen=True)
class Daemon:
    command: list[str]  # argv prefix, e.g. [str(SKILLS_DIR / "file-host/file-host")]
    name: str  # pidfile name and log name
    serves_port: bool
    emits_daemon_died: bool
    public: bool = False  # registers `--public`; anything new is private plus a service key
    service: str | None = None  # vestad service name, when it differs from the command name
    legacy_command: list[str] | None = None  # a script path fleet restart files still launch by
    rig: tp.Callable[[pl.Path, pl.Path], None] | None = None
    env: tuple[tuple[str, str], ...] = ()  # environment this skill's daemon needs on top of the shared one


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _recorded_pid(pidfile: pl.Path) -> int:
    """The pid a record names. The record is "<pid> <starttime>", so reading the whole file as a
    number reaches a daemon only by accident. Raises the way int() and a missing file do, which is
    what the callers already suppress."""
    return int(pidfile.read_text().split()[0])


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
    (skill / "scripts/ensure-deps.sh").symlink_to(SKILLS_DIR / "dashboard/scripts/ensure-deps.sh")
    (skill / "scripts/ensure-build.sh").symlink_to(SKILLS_DIR / "dashboard/scripts/ensure-build.sh")
    # The legacy forwarder execs the launcher through $HOME, so the tree carries it too.
    (skill / "dashboard").symlink_to(SKILLS_DIR / "dashboard/dashboard")
    vite = skill / "app/node_modules/.bin/vite"
    vite.parent.mkdir(parents=True)
    # `vite preview --port <port> --host 0.0.0.0`, so the port is the third argument.
    vite.write_text('#!/bin/sh\nexec python3 -m http.server "$3" --bind 0.0.0.0\n')
    vite.chmod(0o755)
    # Launch reconciles node_modules against the lockfile, so an already-installed box carries a
    # stamp that matches it. Without one the rig would reach for the network on every start.
    lock = skill / "app/package-lock.json"
    lock.write_text("{}\n")
    (skill / "app/node_modules/.vesta-deps").write_text(hashlib.sha256(lock.read_bytes()).hexdigest())
    # Launch also reconciles dist/ against the build inputs. The stamp is written by the real
    # helper under a no-op npx rather than by restating its digest here, then npx is replaced with
    # one that fails: a launcher that rebuilds a bundle already current now fails loudly instead
    # of reaching for the network, which is the property the gate exists to have.
    npx = bin_dir / "npx"
    npx.write_text("#!/bin/sh\nexit 0\n")
    npx.chmod(0o755)
    subprocess.run(
        [str(skill / "scripts/ensure-build.sh")],
        env={**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        check=True,
    )
    npx.write_text('#!/bin/sh\necho "rebuilt a dist that was already current" >&2\nexit 1\n')


def _rig_whatsapp(home: pl.Path, bin_dir: pl.Path) -> None:
    """The launcher runs the cached CLI binary and rebuilds it from source when an input changed,
    so the row needs either the cgo toolchain to build one or a cached binary the launcher accepts
    as current (the Go suite covers the same contract wherever neither is). Where it cannot build,
    a probe run is what tells the two apart: a source edit since the cache was written makes the
    launcher want a compiler it does not have, and the row skips rather than reporting the missing
    toolchain as a contract failure. The caches are the developer's own: a hermetic HOME would
    recompile the whole CLI once per test."""
    real_home = pl.Path(os.environ["HOME"])
    cache_home = pl.Path(os.environ["XDG_CACHE_HOME"]) if "XDG_CACHE_HOME" in os.environ else real_home / ".cache"
    whisper = pl.Path(os.environ["WHISPER_CPP_DIR"] if "WHISPER_CPP_DIR" in os.environ else "/opt/whisper.cpp")
    buildable = (shutil.which("go") or pl.Path("/usr/local/go/bin/go").exists()) and (whisper / "build-static/src/libwhisper.a").exists()
    binary = cache_home / "whatsapp/whatsapp"
    if not binary.exists() and not buildable:
        pytest.skip("no built whatsapp CLI, and no Go toolchain plus whisper static libs to build one")
    for cache in (".cache", "go"):
        (real_home / cache).mkdir(exist_ok=True)
        (home / cache).symlink_to(real_home / cache)
    if buildable:
        return
    probe = subprocess.run(
        [str(SKILLS_DIR / "whatsapp/whatsapp"), "--help"],
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
        check=False,
        timeout=WHATSAPP_PROBE_TIMEOUT,
    )
    if probe.returncode != 0:
        pytest.skip(f"the cached whatsapp CLI at {binary} is stale, and there is no Go toolchain plus whisper static libs to rebuild it")


def _rig_telegram(home: pl.Path, bin_dir: pl.Path) -> None:
    """The launcher compiles the CLI on every invocation, so this row needs the toolchain that
    builds it, not a warm binary (the Go suite covers the same contract wherever it is missing).
    The caches are the developer's own: a hermetic HOME would recompile the whole CLI per test."""
    real_home = pl.Path(os.environ["HOME"])
    if not (shutil.which("go") or pl.Path("/usr/local/go/bin/go").exists()):
        pytest.skip("no Go toolchain to build the telegram CLI")
    for cache in (".cache", "go"):
        (real_home / cache).mkdir(exist_ok=True)
        (home / cache).symlink_to(real_home / cache)


def _rig_ssh(home: pl.Path, bin_dir: pl.Path) -> None:
    """The tunnel is a bore client pointed at the sshd `setup` brought up, so the row stands in
    for both: a bore that stays up, and the sshd port record start reads. A bore already on PATH
    is the one start uses, which is also what keeps this row off the network."""
    bore = bin_dir / "bore"
    bore.write_text("#!/bin/sh\nexec sleep 86400\n")
    bore.chmod(0o755)
    (home / "agent/data/daemons/ssh-tunnel.sshd-port").write_text(str(_free_port()))


SKILLS = [
    Daemon(
        command=[str(SKILLS_DIR / "file-host/file-host")],
        name="file-host",
        serves_port=True,
        emits_daemon_died=False,
        public=True,
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
        legacy_command=[str(SKILLS_DIR / "dashboard/scripts/daemon")],
        rig=_rig_dashboard,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "tasks/cli"), "tasks"],
        name="tasks",
        serves_port=True,
        emits_daemon_died=True,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "reminders/cli"), "reminders"],
        name="reminders",
        serves_port=True,
        emits_daemon_died=True,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "agentmail/cli"), "agentmail"],
        name="agentmail",
        serves_port=True,
        emits_daemon_died=True,
        public=True,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "voice/cli"), "voice-keys"],
        name="voice",
        serves_port=True,
        emits_daemon_died=True,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "app-chat/cli"), "app-chat"],
        name="app-chat",
        serves_port=True,
        emits_daemon_died=True,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "google/cli"), "google"],
        name="google",
        serves_port=False,
        emits_daemon_died=True,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "microsoft/cli"), "microsoft"],
        name="microsoft",
        serves_port=False,
        emits_daemon_died=True,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "email-client/cli"), "email-client"],
        name="email-client",
        serves_port=False,
        emits_daemon_died=True,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "slack/cli"), "slack"],
        name="slack",
        serves_port=False,
        emits_daemon_died=False,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "discord/cli"), "discord"],
        name="discord",
        serves_port=False,
        emits_daemon_died=False,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "tricount/cli"), "tricount"],
        name="tricount",
        serves_port=False,
        emits_daemon_died=True,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "spotify/cli"), "spotify"],
        name="spotify",
        serves_port=False,
        emits_daemon_died=False,
    ),
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "enable-banking/cli"), "finance"],
        name="finance",
        serves_port=False,
        emits_daemon_died=True,
    ),
    Daemon(
        command=[str(SKILLS_DIR / "whatsapp/whatsapp")],
        name="whatsapp",
        serves_port=False,
        emits_daemon_died=True,
        rig=_rig_whatsapp,
        # whatsapp waits minutes for a daemon whose start may compile the CLI first. Here the
        # binary is warm, so a budget well inside the per-verb timeout keeps a start that fails
        # answering with its envelope instead of being killed as a hung command.
        env=(("DAEMON_READY_TIMEOUT_SECS", "30"),),
    ),
    Daemon(
        command=[str(SKILLS_DIR / "telegram/telegram")],
        name="telegram",
        serves_port=False,
        emits_daemon_died=True,
        rig=_rig_telegram,
        # A telegram start compiles the CLI before the daemon it spawns can answer, so the
        # budget covers a warm rebuild and still leaves a start that fails answering with its
        # envelope inside the per-verb timeout. The watchdog's own restarting is its business
        # and not this contract's, so its poll is pushed past the run: one waking up to revive
        # a daemon a test just killed would outlive the test that owns it.
        env=(("DAEMON_READY_TIMEOUT_SECS", "45"), ("TG_WATCHDOG_INTERVAL", "3600")),
    ),
    Daemon(
        command=[str(SKILLS_DIR / "ssh-tunnel/ssh-tunnel")],
        name="ssh-tunnel",
        serves_port=False,
        emits_daemon_died=False,
        rig=_rig_ssh,
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
    if spec.rig:
        spec.rig(home, bin_dir)
    # A skill CLI runs in its own project environment. Whichever venv is running this suite
    # would otherwise capture it: the override redirects the CLI's environment into this one
    # and resyncs it to the skill's lockfile, and the mismatch warning lands on its stderr.
    env = {key: value for key, value in os.environ.items() if key not in ("UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV")}
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env.update(dict(spec.env))
    yield spec, home, env
    # Always tear down: a leaked daemon poisons later tests. Every record, not just this
    # skill's, since one may run a second process (telegram's watchdog) that would outlive the
    # test and restart what this killed. Sorted order puts a "-watchdog" record first.
    for pidfile in sorted((home / "agent/data/daemons").glob("*.pid")):
        with contextlib.suppress(FileNotFoundError, IndexError, ProcessLookupError, ValueError):
            os.kill(_recorded_pid(pidfile), signal.SIGKILL)


def _verb(spec, env, *args):
    return subprocess.run([*spec.command, "daemon", *args], env=env, capture_output=True, text=True, check=False, timeout=60)


def _json(result: subprocess.CompletedProcess[str]):
    """The verb's answer, or the whole run as the evidence when it did not answer in JSON."""
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise AssertionError(f"no JSON answer on stdout: stdout={result.stdout!r} stderr={result.stderr!r}") from None


def _error(stdout: str, stderr: str) -> str:
    """The failure's envelope, or the whole run as the evidence when it did not answer in JSON."""
    try:
        envelope = json.loads(stderr)
    except json.JSONDecodeError:
        raise AssertionError(f"no error envelope on stderr: stdout={stdout!r} stderr={stderr!r}") from None
    assert "error" in envelope, f"the envelope carries no error: stdout={stdout!r} stderr={stderr!r}"
    return envelope["error"]


def _pid(spec, home) -> int | None:
    pidfile = home / "agent/data/daemons" / f"{spec.name}.pid"
    try:
        pid = _recorded_pid(pidfile)
        os.kill(pid, 0)
    except (FileNotFoundError, IndexError, ValueError, ProcessLookupError):
        return None
    return pid


def _death_notices(home) -> list[pl.Path]:
    notif_dir = home / "agent/notifications"
    return list(notif_dir.glob("*daemon_died*")) if notif_dir.exists() else []


def test_start_is_idempotent_and_never_stacks(daemon):
    spec, home, env = daemon
    first = _verb(spec, env, "start")
    assert first.returncode == 0, first.stdout + first.stderr
    assert _json(first) == {"status": "started"}
    pid = _pid(spec, home)
    assert pid is not None
    second = _verb(spec, env, "start")
    assert _json(second) == {"status": "already_running"}
    assert _pid(spec, home) == pid


def test_two_starts_racing_leave_one_daemon_and_one_live_record(daemon):
    """Two starts land at once whenever a restart file and the agent reach for the same daemon.
    The pid record is the mutual exclusion, so exactly one of them brings the daemon up: without
    it both spawn (two daemons, one record naming one of them) or the loser's failure path clears
    the winner's records, and from either state status and stop disagree with what is running."""
    spec, home, env = daemon
    starts = [
        subprocess.Popen([*spec.command, "daemon", "start"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(RACE_STARTS)
    ]
    answers = [start.communicate(timeout=RACE_TIMEOUT) for start in starts]
    brought = 0
    for (out, err), start in zip(answers, starts, strict=True):
        answer = json.loads(out) if out.strip().startswith("{") else None
        if answer == {"status": "started"}:
            brought += 1
        elif answer != {"status": "already_running"}:
            # Anything else has to be loud: a start that neither brought the daemon up nor found
            # one running must fail, never report a success it cannot stand behind.
            assert start.returncode != 0, f"a start answered {out!r} with {err!r}"
            assert err.strip(), f"a start failed silently: {out!r}"
    assert brought == 1, f"{brought} of {RACE_STARTS} starts claim to have brought the daemon up: {[a[0] for a in answers]}"

    pid = _pid(spec, home)
    assert pid is not None, "the record names no live process"
    assert _json(_verb(spec, env, "status"))["running"] is True
    assert _json(_verb(spec, env, "stop")) == {"status": "stopped"}
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_status_rejects_a_reused_pid(daemon):
    """A pid record outlives the container, and the fresh pid namespace renumbers from low values,
    so the recorded pid can belong to an unrelated process by the next boot. os.kill(pid, 0) cannot
    tell the two apart: it answers "does some process hold this pid", never "is this still mine".
    Left undefended, status reports running, the idempotent restart block skips the start, and the
    service is silently down with its one health check reporting health it never measured.

    Standing in for a real reuse: the recorded starttime is edited to a value the live process
    cannot have, which is exactly the state a recycled pid produces."""
    spec, home, env = daemon
    assert _json(_verb(spec, env, "start")) == {"status": "started"}
    pidfile = home / "agent/data/daemons" / f"{spec.name}.pid"

    record = pidfile.read_text().split()
    assert len(record) == 2, f"the record carries no starttime, so a reused pid is undetectable: {record}"
    assert record[1].isdigit(), f"the recorded starttime is not a number: {record}"

    pidfile.write_text(f"{record[0]} {int(record[1]) + 1}")
    assert _json(_verb(spec, env, "status"))["running"] is False, "a reused pid reads as a healthy daemon"

    # And the check is specific: restore the true identity and the same live daemon reads healthy,
    # so this is not a status that simply always says False.
    pidfile.write_text(" ".join(record))
    assert _json(_verb(spec, env, "status"))["running"] is True

    # A record written before this check existed carries a pid alone. It must still read as
    # running, or an upgrade declares every live daemon dead and stacks a second one beside it.
    pidfile.write_text(record[0])
    assert _json(_verb(spec, env, "status"))["running"] is True

    # And a second field that is not a starttime, which no launcher writes but a reader still meets
    # on a truncated or hand-edited record. Comparing a real starttime against it would declare a
    # live daemon dead, so an unparseable second field reads as legacy, not as a mismatch.
    pidfile.write_text(f"{record[0]} x")
    assert _json(_verb(spec, env, "status"))["running"] is True

    pidfile.write_text(" ".join(record))
    assert _json(_verb(spec, env, "stop")) == {"status": "stopped"}


def test_start_fails_closed_when_registration_fails(daemon):
    spec, home, env = daemon
    if not spec.serves_port:
        pytest.skip("portless")
    (pl.Path(env["PATH"].split(":")[0]) / "register-service").write_text("#!/bin/sh\nexit 1\n")
    result = _verb(spec, env, "start")
    assert result.returncode != 0
    error = _error(result.stdout, result.stderr)
    assert isinstance(error, str) and error
    assert not (home / "agent/data/daemons" / f"{spec.name}.pid").exists()


def _spawned_pid(spec, home, start) -> int | None:
    """The pid start records while it waits, read back before the failure path clears it. The
    record holds the claim first and the daemon second, so the last pid it named is the daemon."""
    pidfile = home / "agent/data/daemons" / f"{spec.name}.pid"
    spawned = None
    while start.poll() is None:
        with contextlib.suppress(FileNotFoundError, IndexError, ValueError):
            spawned = _recorded_pid(pidfile)
        time.sleep(PID_CAPTURE_POLL_SECS)
    return spawned


def test_a_start_that_never_gets_an_answer_leaves_nothing_behind(daemon):
    """A daemon that is up but unreachable is the worst of both: with its records in place status
    reads running and every later start declines, so only a stop then a start recovers. The probe
    is aimed at a listener that never answers, which is also what puts a bound on each probe."""
    spec, home, env = daemon
    if not spec.serves_port:
        pytest.skip("portless")
    curl = shutil.which("curl")
    assert curl is not None
    with socket.socket() as mute:
        mute.bind(("127.0.0.1", 0))
        mute.listen(8)
        shim = pl.Path(env["PATH"].split(":")[0]) / "curl"
        shim.write_text(MUTE_CURL.format(curl=curl))
        shim.chmod(0o755)
        unready = {**env, "MUTE_PORT": str(mute.getsockname()[1]), "DAEMON_READY_TIMEOUT_SECS": UNREADY_TIMEOUT_SECS}
        start = subprocess.Popen([*spec.command, "daemon", "start"], env=unready, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        spawned = _spawned_pid(spec, home, start)
        out, err = start.communicate(timeout=120)
    assert start.returncode != 0
    assert _error(out, err)
    assert not (home / "agent/data/daemons" / f"{spec.name}.pid").exists()
    assert not (home / "agent/data/daemons" / f"{spec.name}.port").exists()
    assert spawned is not None
    with pytest.raises(ProcessLookupError):
        os.kill(spawned, 0)


def test_stop_kills_the_process_and_status_tells_the_truth(daemon):
    spec, home, env = daemon
    _verb(spec, env, "start")
    running = _json(_verb(spec, env, "status"))
    assert running["running"] is True
    pid = _pid(spec, home)
    assert pid is not None
    stopped = _verb(spec, env, "stop")
    assert _json(stopped) == {"status": "stopped"}
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert _json(_verb(spec, env, "status"))["running"] is False
    assert _json(_verb(spec, env, "stop")) == {"status": "already_stopped"}


def test_restart_replaces_a_running_daemon_and_starts_a_stopped_one(daemon):
    """The verb a restart file calls, so it has to land on a live daemon either way."""
    spec, home, env = daemon
    assert _json(_verb(spec, env, "start")) == {"status": "started"}
    before = _pid(spec, home)
    assert before is not None
    restarted = _verb(spec, env, "restart")
    assert _json(restarted) == {"status": "started"}, restarted.stdout + restarted.stderr
    after = _pid(spec, home)
    assert after is not None
    assert after != before
    with pytest.raises(ProcessLookupError):
        os.kill(before, 0)
    status = _json(_verb(spec, env, "status"))
    assert status["running"] is True
    if spec.serves_port:
        assert str(status["port"]) == (home / "agent/data/daemons" / f"{spec.name}.port").read_text().strip()

    assert _json(_verb(spec, env, "stop")) == {"status": "stopped"}
    from_stopped = _verb(spec, env, "restart")
    assert _json(from_stopped) == {"status": "started"}, from_stopped.stdout + from_stopped.stderr
    assert _pid(spec, home) is not None
    assert _json(_verb(spec, env, "status"))["running"] is True
    _verb(spec, env, "stop")


def test_deliberate_stop_is_not_reported_as_a_crash(daemon):
    spec, home, env = daemon
    if not spec.emits_daemon_died:
        pytest.skip("does not self-report death")
    assert _json(_verb(spec, env, "start")) == {"status": "started"}
    assert _json(_verb(spec, env, "stop")) == {"status": "stopped"}
    assert _death_notices(home) == []


def test_a_death_nobody_asked_for_is_reported(daemon):
    """The other half of that rule: an exit the daemon did not get asked for has to reach the
    agent, since nothing else notices a daemon that quietly went away."""
    spec, home, env = daemon
    if not spec.emits_daemon_died:
        pytest.skip("does not self-report death")
    assert _json(_verb(spec, env, "start")) == {"status": "started"}
    pid = _pid(spec, home)
    assert pid is not None
    os.kill(pid, signal.SIGINT)
    deadline = time.monotonic() + DEATH_REPORT_TIMEOUT
    while time.monotonic() < deadline and not _death_notices(home):
        time.sleep(DEATH_POLL_SECS)
    assert _death_notices(home) != []


def test_status_reads_the_port_record_and_never_re_registers(daemon):
    """A daemon outlives vestad restarts, so status answers from what start recorded."""
    spec, home, env = daemon
    if not spec.serves_port:
        pytest.skip("portless")
    assert _json(_verb(spec, env, "start")) == {"status": "started"}
    (pl.Path(env["PATH"].split(":")[0]) / "register-service").unlink()
    result = subprocess.run([*spec.command, "daemon", "status"], env=env, capture_output=True, text=True, check=False, timeout=STATUS_TIMEOUT)
    recorded = (home / "agent/data/daemons" / f"{spec.name}.port").read_text().strip()
    assert _json(result) == {"running": True, "port": int(recorded)}
    _verb(spec, env, "stop")


def test_registration_declares_the_expected_exposure(daemon):
    spec, home, env = daemon
    if not spec.serves_port:
        pytest.skip("portless")
    _verb(spec, env, "start")
    args = (home / "register-args").read_text().strip()
    service = spec.service or spec.name
    expected = f"{service} --public" if spec.public else service
    assert args.splitlines()[0] == expected
    _verb(spec, env, "stop")


def test_a_legacy_script_path_still_starts_the_daemon(daemon):
    """A restart file written before the daemon verb launches by script path, and that path
    outlives the sync that converts it, so it has to land on the same daemon."""
    spec, home, env = daemon
    if spec.legacy_command is None:
        pytest.skip("no legacy launch path")
    result = subprocess.run([*spec.legacy_command, "start"], env=env, capture_output=True, text=True, check=False, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _json(result) == {"status": "started"}
    assert _pid(spec, home) is not None
    assert _json(_verb(spec, env, "status"))["running"] is True
    _verb(spec, env, "stop")


def _is_error_envelope(output: str) -> bool:
    """Whether output is the `{"error":...}` object a verb answers a real failure with."""
    try:
        return "error" in json.loads(output)
    except json.JSONDecodeError:
        return False


def test_usage_and_unknown_verbs(daemon):
    spec, _home, env = daemon
    for args in ([], ["-h"], ["--help"], ["help"], ["daemon"], ["daemon", "help"]):
        result = subprocess.run([*spec.command, *args], env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 0
        # A skill whose command is a CLI answers with that CLI's own help.
        assert "usage" in result.stdout.lower()
    # A verb that does not exist is the caller's typo: usage, non-zero, and never the error
    # envelope, which a caller reads as a daemon that failed and may be worth retrying.
    unknown = _verb(spec, env, "bogus")
    assert unknown.returncode != 0
    output = unknown.stdout + unknown.stderr
    assert "usage" in output.lower(), f"an unknown verb answered without usage: {output!r}"
    assert not _is_error_envelope(output), f"an unknown verb answered with the error envelope: {output!r}"


def test_every_python_daemon_child_is_launched_unbuffered():
    """A daemon that re-execs its own CLI must hand the child PYTHONUNBUFFERED.

    CPython block-buffers stdout when it is a file rather than a tty, so a detached daemon writing
    to `~/agent/logs/<name>.log` can print its startup line and poll for hours while the log stays
    empty and its mtime stays stale. That is not a cosmetic loss: the log is the only evidence of a
    daemon's liveness anyone reads, so a stale mtime gets diagnosed as a daemon that died. Observed
    on a live box, where the finance watcher had been polling for over an hour with its log
    untouched since the previous day.

    Checked over the source rather than a running process because this file is duplicated per
    skill, so the failure returns the moment a twelfth copy is added. A runtime check would have to
    know which daemons print on startup, and a daemon that prints nothing would pass by saying
    nothing, which is the shape of test that lets this class of bug through.
    """
    # Re-execing the CLI is what names the daemons this applies to: one that spawns a compiled
    # binary is not running an interpreter, so its buffering is not in play. Matched over the whole
    # file rather than the call, so a reformatted Popen cannot quietly stop being checked.
    sources = {path: path.read_text() for path in sorted(SKILLS_DIR.rglob("daemon.py"))}
    reexecs = {path: source for path, source in sources.items() if "[sys.argv[0]" in source}
    assert reexecs, "no daemon re-execs its own CLI, so this check is matching nothing"
    offenders = [str(path.relative_to(REPO_ROOT)) for path, source in reexecs.items() if "PYTHONUNBUFFERED" not in source]
    assert offenders == [], f"daemon children launched with buffered stdout: {offenders}"


def test_no_daemon_claims_the_pidfile_with_a_bare_pid():
    """The claim writes the same self-verifying record the finished start does.

    A start claims the pidfile, registers its port with vestad, then spawns and records the child.
    A start killed inside that window leaves the record it claimed with standing. Written bare, it
    names a dead starter with no starttime to check, so a pid recycled before the next boot reads
    as a healthy daemon and every later start declines: the exact failure the record exists to
    catch. Writing the full record at claim time is also what lets records converge, so the
    bare-pid fallback can eventually be removed.
    """
    python = {path: path.read_text() for path in sorted(SKILLS_DIR.rglob("daemon.py"))}
    python = {path: source for path, source in python.items() if "def _claim(" in source}
    assert python, "no python daemon claims a pidfile, so this check is matching nothing"

    # A skill with no CLI project is one executable named after its directory (AGENTS.md), which is
    # what the sh launchers are; self-selecting on claim_start keeps this from drifting off a list.
    launchers = {path: path.read_text() for path in sorted(SKILLS_DIR.glob("*/*")) if path.name == path.parent.name}
    shell = {path: source for path, source in launchers.items() if "claim_start()" in source}
    assert shell, "no sh launcher claims a pidfile, so this check is matching nothing"

    bare = [str(path.relative_to(REPO_ROOT)) for path, source in python.items() if "handle.write(str(pid))" in source]
    bare += [str(path.relative_to(REPO_ROOT)) for path, source in shell.items() if 'echo $$ > "$PIDFILE"' in source]
    assert bare == [], f"a claim writing a bare pid leaves an unverifiable record if the start dies mid-window: {bare}"
