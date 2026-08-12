"""Behavioral tests for the restart skill's start-daemons.sh.

The script reads the daemon list from daemons.sh on disk and runs every line.
The property that matters most: a line that is not a working daemon command is
reported as a failure, never silently skipped, because a silent skip is the
exact failure this script exists to remove.
"""

import os
import pathlib as pl
import subprocess

SCRIPT = pl.Path(__file__).parent.parent / "skills" / "restart" / "start-daemons.sh"

STUBS = {
    "started-daemon": '#!/bin/sh\necho \'{"status":"started"}\'\n',
    "running-daemon": '#!/bin/sh\necho \'{"status":"already_running"}\'\n',
    "failing-daemon": '#!/bin/sh\necho \'{"error":"boom"}\' >&2\nexit 1\n',
    "echo-daemon": '#!/bin/sh\necho \'{"status":"started"}\' "$@"\n',
}


def _run(tmp_path: pl.Path, daemons_content: str | None) -> subprocess.CompletedProcess[str]:
    restart_dir = tmp_path / "restart"
    restart_dir.mkdir()
    (restart_dir / "start-daemons.sh").write_text(SCRIPT.read_text())
    if daemons_content is not None:
        (restart_dir / "daemons.sh").write_text(daemons_content)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", str(restart_dir / "start-daemons.sh")],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_missing_list_is_a_noop(tmp_path: pl.Path) -> None:
    result = _run(tmp_path, None)
    assert result.returncode == 0
    assert "nothing to start" in result.stdout


def test_comment_only_list_is_a_noop(tmp_path: pl.Path) -> None:
    result = _run(tmp_path, "#!/usr/bin/env bash\n# no daemons yet\n")
    assert result.returncode == 0
    assert "nothing to start" in result.stdout


def test_all_daemons_up_exits_zero(tmp_path: pl.Path) -> None:
    result = _run(tmp_path, "started-daemon daemon start\nrunning-daemon daemon start\n")
    assert result.returncode == 0
    assert "started-daemon" in result.stdout
    assert "running-daemon" in result.stdout
    assert result.stderr == ""


def test_failing_daemon_reported_on_stderr_and_others_still_run(tmp_path: pl.Path) -> None:
    # Failing line first: the good line after it must still run, so a mid-list failure never
    # aborts the rest, and the failure lands on stderr with a non-zero exit.
    result = _run(tmp_path, "failing-daemon daemon start\nstarted-daemon daemon start\n")
    assert result.returncode == 1
    assert "started-daemon" in result.stdout
    assert "failing-daemon" in result.stderr
    assert "boom" in result.stderr


def test_malformed_line_fails_loud_not_silent(tmp_path: pl.Path) -> None:
    # A line that is not a real command must be reported, never silently dropped.
    result = _run(tmp_path, "not-a-daemon-command foo bar\n")
    assert result.returncode == 1
    assert "not-a-daemon-command" in result.stderr


def test_flags_passed_verbatim(tmp_path: pl.Path) -> None:
    result = _run(tmp_path, "echo-daemon daemon start --instance personal --read-only\n")
    assert result.returncode == 0
    assert "--instance personal --read-only" in result.stdout
