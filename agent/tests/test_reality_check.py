"""The dream's reality check probes the running system, not the dream's own record."""

import os
import pathlib as pl
import re
import subprocess
import time

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


def test_live_daemon_record_stays_green(tmp_path):
    # The record is "<pid> <starttime>", two fields. Reading the whole file as the pid hands kill a
    # word it cannot parse, and every live daemon on the box reports RED on a healthy night.
    home = _healthy_home(tmp_path)
    (home / "agent" / "data" / "daemons" / "alive.pid").write_text(f"{os.getpid()} 12345")

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK  daemon alive is running" in run.stdout


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
    # Pins the context branch itself: dropping to the plain OK line would also pass the figures.
    assert "not yours to clear" in run.stdout


def test_a_du_walk_that_never_finishes_goes_red(tmp_path):
    # The walk is bounded by `timeout`, so a pathological tree or a stuck filesystem cannot hang
    # the dream; the shim stands in for the bound firing (exit 124) without waiting it out.
    home = _healthy_home(tmp_path)
    fake_timeout = home / "bin" / "timeout"
    fake_timeout.write_text("#!/bin/sh\nexit 124\n")
    fake_timeout.chmod(0o755)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED sizing" in run.stdout


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


def _dreamer_summary(home: pl.Path, hours_old: float) -> pl.Path:
    summary = home / "agent" / "dreamer"
    summary.mkdir(parents=True, exist_ok=True)
    written = summary / "2026-01-01.md"
    written.write_text("summary")
    aged = time.time() - hours_old * 3600
    os.utime(written, (aged, aged))
    return written


def test_a_recent_dreamer_summary_stays_green(tmp_path):
    home = _healthy_home(tmp_path)
    _dreamer_summary(home, 17)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK  last dreamer summary 17h old" in run.stdout


def test_a_summary_a_night_late_stays_green(tmp_path):
    # The bound is 30h rather than 24h on purpose: a nightly cadence is exactly 24h, so a run that
    # slips a few hours would report RED on a box that never missed a night.
    home = _healthy_home(tmp_path)
    _dreamer_summary(home, 26)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "cadence intact" in run.stdout


def test_a_missed_night_goes_red(tmp_path):
    home = _healthy_home(tmp_path)
    _dreamer_summary(home, 40)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED last dreamer summary is 40h old" in run.stdout


def test_a_box_that_has_never_dreamed_stays_green(tmp_path):
    """A fresh box has no summaries at all, and a probe that reads that as a missed night is red
    from birth with nothing the agent can do about it."""
    run = _run(_healthy_home(tmp_path))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "no dreamer summaries yet" in run.stdout


def test_the_documented_checkpoint_lookup_finds_a_differently_worded_commit(tmp_path):
    """The curation review's baseline is found by a grep written in the skill, and the commit
    subject it looks for is a convention nothing enforces. Pinned by running the documented
    pattern against a real repo whose checkpoint is worded off-convention: a pattern that only
    matches the conventional wording finds nothing, and the review then diffs against an older
    tree while reporting success."""
    skill = SCRIPT.parents[1] / "SKILL.md"
    line = next(ln for ln in skill.read_text().splitlines() if "--grep" in ln and "checkpoint" in ln)
    pattern = re.search(r"--grep '([^']+)'", line).group(1)

    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "config", "user.email", "t@example.com"], check=True)
    subprocess.run([*git, "config", "user.name", "t"], check=True)
    (repo / "f").write_text("x")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "dream 7 Aug: preflight script, memory, personality"], check=True)

    found = subprocess.run([*git, "log", "-n1", "--format=%H", "--grep", pattern], capture_output=True, text=True, check=True)

    assert found.stdout.strip(), f"the documented pattern {pattern!r} misses an off-convention checkpoint"
