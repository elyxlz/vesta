"""The dream's reality check probes the running system, not the dream's own record."""

import os
import pathlib as pl
import subprocess

SCRIPT = pl.Path(__file__).resolve().parents[1] / "skills" / "dream" / "scripts" / "reality_check.sh"


def _run(home: pl.Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(home), "PATH": f"{home / 'bin'}:{os.environ['PATH']}"}
    return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60, check=False)


def _fake_disk_usage(home: pl.Path, percent: int) -> None:
    # The disk probe reads df, the one probe that sees the host rather than $HOME, so tests pin it
    # via a PATH shim to stay hermetic on any machine.
    fake_df = home / "bin" / "df"
    fake_df.write_text(
        f'#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted"\necho "/dev/fake 100 {percent} 0 {percent}% /"\n'
    )
    fake_df.chmod(0o755)


def _fake_own_usage(home: pl.Path, megabytes: int) -> None:
    # The probe sums `du -sm $HOME /tmp`, and the real /tmp belongs to the machine running the
    # tests, so this is pinned for the same reason df is.
    fake_du = home / "bin" / "du"
    fake_du.write_text(f'#!/bin/sh\necho "{megabytes} {home}"\necho "0 /tmp"\n')
    fake_du.chmod(0o755)


def _healthy_home(tmp_path: pl.Path) -> pl.Path:
    (tmp_path / "bin").mkdir()
    (tmp_path / "agent" / "data" / "daemons").mkdir(parents=True)
    (tmp_path / "agent" / "logs").mkdir(parents=True)
    (tmp_path / "agent" / "notifications").mkdir(parents=True)
    (tmp_path / "agent" / "data" / "events.db").write_text("stub")
    _fake_disk_usage(tmp_path, 42)
    _fake_own_usage(tmp_path, 512)
    return tmp_path


def test_healthy_box_exits_green(tmp_path):
    # The healthy case is exercised on purpose: a check that cannot pass green is as broken as one
    # that cannot fail.
    run = _run(_healthy_home(tmp_path))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "RED" not in run.stdout
    assert "all probes green" in run.stdout


def test_dead_daemon_record_goes_red(tmp_path):
    home = _healthy_home(tmp_path)
    (home / "agent" / "data" / "daemons" / "ghost.pid").write_text("99999999")

    run = _run(home)

    assert run.returncode == 1
    assert "RED daemon ghost" in run.stdout


def test_error_storm_in_a_recent_log_goes_red(tmp_path):
    # The RED must survive the loop: a counter incremented in a pipeline subshell is lost by the
    # time the exit code is computed, which turns a red probe into a green exit.
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "stormy.log").write_text("ERROR boom\n" * 300)

    run = _run(home)

    assert run.returncode == 1
    assert "RED stormy.log" in run.stdout


def test_quiet_recent_log_stays_green(tmp_path):
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "calm.log").write_text("INFO fine\n" * 300)

    run = _run(home)

    assert run.returncode == 0
    assert "OK  calm.log" in run.stdout


def test_this_agent_filling_the_disk_goes_red(tmp_path):
    home = _healthy_home(tmp_path)
    _fake_disk_usage(home, 95)
    _fake_own_usage(home, 25_000)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "25000MB" in run.stdout


def test_a_full_host_disk_this_agent_did_not_fill_stays_green(tmp_path):
    """A RED the agent cannot clear teaches it to carry REDs, which is the one thing the probe
    forbids. The host figure still gets reported, as context rather than as a fault."""
    home = _healthy_home(tmp_path)
    _fake_disk_usage(home, 95)
    _fake_own_usage(home, 300)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "95%" in run.stdout
    assert "300MB" in run.stdout


def test_wal_only_writes_keep_events_db_green(tmp_path):
    # The store runs in WAL mode: between checkpoints commits touch only the -wal sibling, so a
    # stale main file with a fresh -wal is a healthy box, not a recording failure.
    home = _healthy_home(tmp_path)
    db = home / "agent" / "data" / "events.db"
    stale = 1_000_000_000
    os.utime(db, (stale, stale))
    (home / "agent" / "data" / "events.db-wal").write_text("wal")

    run = _run(home)

    assert run.returncode == 0
    assert "OK  events.db" in run.stdout


def test_stale_events_db_goes_red(tmp_path):
    home = _healthy_home(tmp_path)
    db = home / "agent" / "data" / "events.db"
    stale = 1_000_000_000  # far past the 24h freshness window
    os.utime(db, (stale, stale))

    run = _run(home)

    assert run.returncode == 1
    assert "RED events.db" in run.stdout
