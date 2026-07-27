"""Exercises the REAL vestad/scripts/daemon-lifecycle against a fake screen/curl/register-service.

The fake screen tracks a live session as a marker file, so start/stop/status and the readiness
poll are proven deterministically without spawning real sessions or sleeping.
"""

import json
import os
import pathlib as pl
import subprocess

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "agent/skills/vestad/scripts/daemon-lifecycle"

FAKE_SCREEN = """#!/bin/sh
# Tracks a "live session" as a marker file under $SCREEN_STATE_DIR, and records
# each launched command so tests can assert what the runner actually spawned.
case "$1" in
  -ls)
    printed=0
    for f in "$SCREEN_STATE_DIR"/*.live; do
      [ -e "$f" ] || continue
      if [ "$printed" -eq 0 ]; then
        echo "There are screens on:"
        printed=1
      fi
      name=$(basename "$f" .live)
      printf '\\t12345.%s\\t(Detached)\\n' "$name"
    done
    [ "$printed" -eq 0 ] && echo "No Sockets found in /run/screen/S-root."
    ;;
  -wipe) ;;
  -dmS)
    session="$2"
    shift 2
    touch "$SCREEN_STATE_DIR/$session.live"
    printf '%s\\n' "$*" >> "$SCREEN_STATE_DIR/launched"
    if [ -n "${FAKE_SCREEN_DIES:-}" ]; then
      rm -f "$SCREEN_STATE_DIR/$session.live"
    fi
    ;;
  -S)
    rm -f "$SCREEN_STATE_DIR/$2.live"
    ;;
esac
"""

FAKE_CURL = """#!/bin/sh
count_file="$SCREEN_STATE_DIR/curl-calls"
count=$(($(cat "$count_file" 2>/dev/null || echo 0) + 1))
echo "$count" > "$count_file"
if [ "$count" -le "${FAKE_CURL_FAIL_FIRST:-0}" ]; then
  exit 7
fi
exit "${FAKE_CURL_EXIT:-0}"
"""

FAKE_REGISTER_SERVICE = """#!/bin/sh
if [ -n "${FAKE_REGISTER_FAILS:-}" ]; then
  echo "vestad unreachable" >&2
  exit 1
fi
printf '%s\\n' "$*" >> "$SCREEN_STATE_DIR/registered"
echo "${FAKE_PORT:-4321}"
"""


def _rig(tmp_path):
    """Fake $HOME plus fake screen/curl on PATH; returns the env for subprocess."""
    home = tmp_path / "home"
    (home / "agent/skills/vestad/scripts").mkdir(parents=True)
    register_service = home / "agent/skills/vestad/scripts/register-service"
    register_service.write_text(FAKE_REGISTER_SERVICE)
    register_service.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("screen", FAKE_SCREEN), ("curl", FAKE_CURL)):
        script = bin_dir / name
        script.write_text(body)
        script.chmod(0o755)

    screen_state = tmp_path / "screen-state"
    screen_state.mkdir()

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["SCREEN_STATE_DIR"] = str(screen_state)
    return env


def _run(env, *args):
    return subprocess.run([str(RUNNER), *args], env=env, capture_output=True, text=True, check=False)


def _launched(tmp_path):
    return (tmp_path / "screen-state/launched").read_text()


def test_start_launches_the_session(tmp_path):
    env = _rig(tmp_path)
    result = _run(env, "start", "--session", "widget", "--", "widget", "serve")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "started"}
    assert "widget serve" in _launched(tmp_path)


def test_start_is_idempotent(tmp_path):
    env = _rig(tmp_path)
    _run(env, "start", "--session", "widget", "--", "widget", "serve")
    second = _run(env, "start", "--session", "widget", "--", "widget", "serve")
    assert json.loads(second.stdout) == {"status": "already_running"}
    assert _launched(tmp_path).count("widget serve") == 1


def test_start_fails_when_the_daemon_exits_immediately(tmp_path):
    env = _rig(tmp_path)
    env["FAKE_SCREEN_DIES"] = "1"
    result = _run(env, "start", "--session", "widget", "--", "widget", "serve")
    assert result.returncode != 0
    assert "error" in json.loads(result.stderr)


def test_start_refuses_to_launch_when_registration_fails(tmp_path):
    env = _rig(tmp_path)
    env["FAKE_REGISTER_FAILS"] = "1"
    result = _run(env, "start", "--session", "widget", "--service", "widget", "--port-mode", "private", "--", "widget", "serve")
    assert result.returncode != 0
    assert not (tmp_path / "screen-state/launched").exists()


def test_private_and_public_registration_differ(tmp_path):
    env = _rig(tmp_path)
    _run(env, "start", "--session", "a", "--service", "a", "--port-mode", "private", "--", "a", "serve")
    _run(env, "start", "--session", "b", "--service", "b", "--port-mode", "public", "--", "b", "serve")
    registered = (tmp_path / "screen-state/registered").read_text().splitlines()
    assert registered[0] == "a"
    assert registered[1] == "b --public"


def test_launch_command_receives_the_registered_port(tmp_path):
    env = _rig(tmp_path)
    env["FAKE_PORT"] = "61999"
    _run(env, "start", "--session", "widget", "--service", "widget", "--port-mode", "private", "--", "widget", "serve")
    assert "61999" in _launched(tmp_path)


def test_start_polls_until_the_probe_answers(tmp_path):
    env = _rig(tmp_path)
    env["FAKE_CURL_FAIL_FIRST"] = "3"
    result = _run(
        env, "start", "--session", "widget", "--service", "widget", "--port-mode", "private", "--probe", "http", "--", "widget", "serve"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert int((tmp_path / "screen-state/curl-calls").read_text()) == 4


def test_stop_writes_the_marker_then_quits(tmp_path):
    env = _rig(tmp_path)
    marker = tmp_path / "stop-requested"
    _run(env, "start", "--session", "widget", "--", "widget", "serve")
    result = _run(env, "stop", "--session", "widget", "--stop-marker", str(marker))
    assert json.loads(result.stdout) == {"status": "stopped"}
    assert marker.exists()


def test_stop_is_idempotent(tmp_path):
    env = _rig(tmp_path)
    result = _run(env, "stop", "--session", "widget")
    assert json.loads(result.stdout) == {"status": "already_stopped"}


def test_start_clears_a_stale_stop_marker(tmp_path):
    env = _rig(tmp_path)
    marker = tmp_path / "stop-requested"
    marker.write_text("")
    _run(env, "start", "--session", "widget", "--stop-marker", str(marker), "--", "widget", "serve")
    assert not marker.exists()


def test_status_reports_running_port_and_probe(tmp_path):
    env = _rig(tmp_path)
    env["FAKE_PORT"] = "9999"
    _run(env, "start", "--session", "widget", "--service", "widget", "--port-mode", "private", "--probe", "http", "--", "widget", "serve")
    status = json.loads(_run(env, "status", "--session", "widget", "--service", "widget", "--port-mode", "private", "--probe", "http").stdout)
    assert status == {"running": True, "session": "widget", "port": "9999", "http_ok": True}


def test_status_on_a_stopped_daemon(tmp_path):
    env = _rig(tmp_path)
    status = json.loads(_run(env, "status", "--session", "widget").stdout)
    assert status == {"running": False, "session": "widget", "port": None, "http_ok": False}


def test_restart_relaunches_the_session(tmp_path):
    env = _rig(tmp_path)
    _run(env, "start", "--session", "widget", "--", "widget", "serve")
    result = _run(env, "restart", "--session", "widget", "--", "widget", "serve")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "started"}
    assert _launched(tmp_path).count("widget serve") == 2


def test_unknown_action_exits_nonzero(tmp_path):
    env = _rig(tmp_path)
    result = _run(env, "bogus", "--session", "widget")
    assert result.returncode != 0


def test_session_is_required(tmp_path):
    env = _rig(tmp_path)
    result = _run(env, "start", "--", "widget", "serve")
    assert result.returncode != 0
