"""Exercises the REAL dashboard scripts/daemon and scripts/setup.sh against a fake
screen/curl/register-service, mirroring the telegram/tasks lifecycle transplant."""

import json
import os
import pathlib as pl
import shutil
import subprocess

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
DAEMON = REPO_ROOT / "agent/skills/dashboard/scripts/daemon"
SETUP = REPO_ROOT / "agent/skills/dashboard/scripts/setup.sh"

FAKE_SCREEN = """#!/bin/sh
# Tracks a "live session" as a marker file under $SCREEN_STATE_DIR.
case "$1" in
  -ls)
    if [ -f "$SCREEN_STATE_DIR/dashboard.live" ]; then
      echo "There are screens on:"
      printf '\\t12345.dashboard\\t(Detached)\\n'
    else
      echo "No Sockets found in /run/screen/S-root."
    fi
    ;;
  -wipe) ;;
  -dmS)
    touch "$SCREEN_STATE_DIR/$2.live"
    ;;
  -S)
    rm -f "$SCREEN_STATE_DIR/$2.live"
    ;;
esac
"""

FAKE_CURL = """#!/bin/sh
# Counts calls in $SCREEN_STATE_DIR/curl-calls; fails the first
# $FAKE_CURL_FAIL_FIRST calls so tests can pin readiness polling.
count_file="$SCREEN_STATE_DIR/curl-calls"
count=$(($(cat "$count_file" 2>/dev/null || echo 0) + 1))
echo "$count" > "$count_file"
if [ "$count" -le "${FAKE_CURL_FAIL_FIRST:-0}" ]; then
  exit 7
fi
exit "${FAKE_CURL_EXIT:-0}"
"""

FAKE_REGISTER_SERVICE = """#!/bin/sh
echo "${FAKE_DASHBOARD_PORT:-4321}"
"""


def _rig(tmp_path):
    """Builds a fake $HOME plus a fake screen/curl on PATH, returns the env for subprocess."""
    home = tmp_path / "home"
    (home / "agent/skills/vestad/scripts").mkdir(parents=True)
    (home / "agent/skills/restart").mkdir(parents=True)
    register_service = home / "agent/skills/vestad/scripts/register-service"
    register_service.write_text(FAKE_REGISTER_SERVICE)
    register_service.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    screen = bin_dir / "screen"
    screen.write_text(FAKE_SCREEN)
    screen.chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(0o755)

    screen_state = tmp_path / "screen-state"
    screen_state.mkdir()

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["SCREEN_STATE_DIR"] = str(screen_state)
    return env


def _run(script, args, env):
    return subprocess.run([str(script), *args], env=env, capture_output=True, text=True, check=False)


def test_daemon_start_is_idempotent(tmp_path):
    env = _rig(tmp_path)
    first = _run(DAEMON, ["start"], env)
    assert first.returncode == 0, first.stdout + first.stderr
    assert json.loads(first.stdout) == {"status": "started"}

    second = _run(DAEMON, ["start"], env)
    assert second.returncode == 0
    assert json.loads(second.stdout) == {"status": "already_running"}


def test_daemon_start_polls_until_the_server_answers(tmp_path):
    env = _rig(tmp_path)
    env["FAKE_CURL_FAIL_FIRST"] = "3"
    result = _run(DAEMON, ["start"], env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "started"}
    assert int((tmp_path / "screen-state/curl-calls").read_text()) == 4


def test_daemon_status_reports_running_port_and_http(tmp_path):
    env = _rig(tmp_path)
    env["FAKE_DASHBOARD_PORT"] = "9999"
    _run(DAEMON, ["start"], env)

    status = _run(DAEMON, ["status"], env)
    assert status.returncode == 0, status.stdout + status.stderr
    body = json.loads(status.stdout)
    assert body == {"running": True, "session": "dashboard", "port": "9999", "http_ok": True}


def test_daemon_status_when_stopped_reports_no_port(tmp_path):
    env = _rig(tmp_path)
    status = _run(DAEMON, ["status"], env)
    assert status.returncode == 0
    assert json.loads(status.stdout) == {"running": False, "session": "dashboard", "port": None, "http_ok": False}


def test_daemon_status_running_but_probe_failing_is_not_http_ok(tmp_path):
    env = _rig(tmp_path)
    _run(DAEMON, ["start"], env)
    env["FAKE_CURL_EXIT"] = "22"

    status = _run(DAEMON, ["status"], env)
    body = json.loads(status.stdout)
    assert body["running"] is True
    assert body["http_ok"] is False


def test_daemon_stop_is_idempotent(tmp_path):
    env = _rig(tmp_path)
    already = _run(DAEMON, ["stop"], env)
    assert already.returncode == 0
    assert json.loads(already.stdout) == {"status": "already_stopped"}

    _run(DAEMON, ["start"], env)
    stopped = _run(DAEMON, ["stop"], env)
    assert stopped.returncode == 0
    assert json.loads(stopped.stdout) == {"status": "stopped"}
    assert json.loads(_run(DAEMON, ["status"], env).stdout)["running"] is False


def test_bare_invocation_and_help_print_usage_and_exit_zero(tmp_path):
    env = _rig(tmp_path)
    for args in ([], ["--help"], ["-h"], ["help"]):
        result = _run(DAEMON, args, env)
        assert result.returncode == 0, f"{args}: {result.stdout + result.stderr}"
        assert "Usage" in result.stdout


def test_unknown_subcommand_exits_nonzero(tmp_path):
    env = _rig(tmp_path)
    result = _run(DAEMON, ["bogus"], env)
    assert result.returncode != 0


def test_setup_starts_daemon_and_appends_restart_line_once(tmp_path):
    env = _rig(tmp_path)
    # Copy the skill scripts into tmp_path (preserving the scripts/../app layout)
    # and pre-seed the app build artifacts there, so setup.sh never shells out to
    # npm/vite and the test never touches the real checkout.
    skill_dir = tmp_path / "dashboard"
    shutil.copytree(SETUP.parent, skill_dir / "scripts")
    (skill_dir / "app/node_modules").mkdir(parents=True)
    (skill_dir / "app/dist").mkdir(parents=True)
    setup = skill_dir / "scripts/setup.sh"

    restart_skill = pl.Path(env["HOME"]) / "agent/skills/restart/SKILL.md"
    restart_skill.write_text("# Restart\n\n## Daemons\n")

    first = subprocess.run(["sh", str(setup)], env=env, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stdout + first.stderr
    assert json.loads(_run(DAEMON, ["status"], env).stdout)["running"] is True

    line = "running dashboard || { ~/agent/skills/dashboard/scripts/daemon start; sleep 1; }"
    content_after_first = restart_skill.read_text()
    assert content_after_first.count(line) == 1

    second = subprocess.run(["sh", str(setup)], env=env, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stdout + second.stderr
    assert restart_skill.read_text().count(line) == 1
