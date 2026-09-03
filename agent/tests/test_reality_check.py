"""The dream's reality check probes the running system, not the dream's own record."""

import os
import pathlib as pl
import subprocess
import time

SCRIPT = pl.Path(__file__).resolve().parents[1] / "skills" / "dream" / "scripts" / "reality_check.sh"

# The agent log's file formatter colours every line, so a real line never starts with its date.
GREEN = "\x1b[2;32m"
RESET = "\x1b[0m"


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


def _day(days_ago: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - days_ago * 86400))


def _usage_line(day: str, *, cache_read: int) -> str:
    return f"{GREEN}{day} 03:00:00 [SYSTEM] [USAGE] in=0 out=0 cache_read={cache_read} cache_write=0 | duration=2.1s{RESET}\n"


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


def test_error_storm_survives_nul_bytes_in_the_log(tmp_path):
    # An unclean write leaves NUL bytes in a log, which grep reads as binary; the storm still counts.
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "truncated.log").write_bytes(b"INFO fine\n" * 10 + b"\x00" * 200 + b"\nERROR boom\n" * 300)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED truncated.log" in run.stdout


def test_agent_narration_does_not_count_as_an_error_storm(tmp_path):
    # vesta.log interleaves daemon output with the agent's own narration, so a day spent reading
    # about ERROR correction must not be indistinguishable from a component failing all night.
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "vesta.log").write_text("[AGENT] reading about Reed-Solomon ERROR correction\n" * 260)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK  vesta.log: 0 error lines in the last 2 days" in run.stdout


def test_an_untagged_daemon_log_still_storms(tmp_path):
    # The exclusion subtracts [AGENT]; it must not become a whitelist for [SYSTEM], or the five
    # daemon logs that carry neither tag would score zero forever and never RED again.
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "whatsapp.log").write_text("ERROR send failed\n" * 260)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED whatsapp.log" in run.stdout


def test_quiet_recent_log_stays_green(tmp_path):
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "calm.log").write_text("INFO fine\n" * 300)

    run = _run(home)

    assert run.returncode == 0
    assert "OK  calm.log" in run.stdout


def test_undated_traceback_lines_count_with_the_dated_line_above_them(tmp_path):
    """A traceback's body carries no timestamp of its own, so requiring the date on every counted
    line hides a live multi-line storm under the threshold."""
    home = _healthy_home(tmp_path)
    block = f"{_day(0)} 01:00:00 ERROR boom\nTraceback (most recent call last):\n  raise ValueError\n"
    (home / "agent" / "logs" / "tb.log").write_text(block * 80)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED tb.log" in run.stdout


def test_errors_dated_days_ago_age_out_of_a_still_fresh_log(tmp_path):
    # The count is aged by the line dates, not the file mtime: a component fixed days ago keeps
    # appending healthy lines to the same file, and its old storm must not stay loud.
    home = _healthy_home(tmp_path)
    lines = f"{_day(3)} 01:00:00 ERROR boom\n" * 300 + f"{_day(0)} 01:00:00 INFO recovered\n"
    (home / "agent" / "logs" / "healed.log").write_text(lines)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK  healed.log" in run.stdout


def test_a_colour_coded_log_still_ages_by_its_dates(tmp_path):
    # The agent log's own lines start with a colour code, not the date; the aging pass must still
    # see the date behind it, or every old storm in vesta.log counts forever.
    home = _healthy_home(tmp_path)
    lines = f"{GREEN}{_day(3)} 01:00:00 [SYSTEM] [RUNTIME] ERROR boom{RESET}\n" * 300
    (home / "agent" / "logs" / "vesta.log").write_text(lines)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK  vesta.log: 0 error lines" in run.stdout


def test_healthy_zero_count_summaries_do_not_count_as_errors(tmp_path):
    # "45 matching, 0 new, 0 error(s)" carries the word without reporting a failure.
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "sync.log").write_text("45 matching, 0 new, 0 error(s)\n" * 300)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK  sync.log: 0 error lines" in run.stdout


def test_a_zero_count_next_to_a_nonzero_count_still_counts(tmp_path):
    """The healthy-summary filter must not overshoot: a line naming a real nonzero count alongside
    a zero one is a storm, not a healthy summary."""
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "mixed.log").write_text("summary: 0 warnings, 47 errors this cycle\n" * 300)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED mixed.log" in run.stdout


def test_a_zero_identifier_before_the_word_error_still_counts(tmp_path):
    # "worker 0 error: connection refused" is a real error whose worker id happens to be zero.
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "worker.log").write_text("worker 0 error: connection refused\n" * 300)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED worker.log" in run.stdout


def test_a_day_of_refused_turns_goes_red(tmp_path):
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "vesta.log").write_text(_usage_line(_day(0), cache_read=0) * 3)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED the provider refused 3 turns today" in run.stdout


def test_a_lone_refused_turn_stays_green(tmp_path):
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "vesta.log").write_text(_usage_line(_day(0), cache_read=0))

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK  the provider refused 1 turns today" in run.stdout


def test_turns_that_ran_and_yesterdays_refusals_are_not_refused_turns(tmp_path):
    # A turn that ran and chose silence still reads its cache; a refusal on another day is that
    # day's finding, not tonight's.
    home = _healthy_home(tmp_path)
    lines = _usage_line(_day(0), cache_read=433470) * 5 + _usage_line(_day(1), cache_read=0) * 5
    (home / "agent" / "logs" / "vesta.log").write_text(lines)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK  the provider refused 0 turns today" in run.stdout


def test_this_agent_filling_the_disk_goes_red(tmp_path):
    home = _healthy_home(tmp_path)
    _fake_disk_usage(home, 95)
    _fake_own_usage(home, 25_000)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "25000MB" in run.stdout


def test_a_large_footprint_without_disk_pressure_stays_green(tmp_path):
    """Own usage alone is a size, not a problem: a corpus-holding agent on a half-empty disk must
    not read RED every night, because a permanent RED teaches the reader to skim the one output
    that exists to stop skimming."""
    home = _healthy_home(tmp_path)
    _fake_disk_usage(home, 50)
    _fake_own_usage(home, 25_000)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "size without pressure" in run.stdout
    assert "25000MB" in run.stdout


def test_a_busy_host_disk_this_agent_did_not_fill_stays_green(tmp_path):
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


def test_a_host_disk_at_the_ceiling_goes_red(tmp_path):
    """Above the context band the host figure is the agent's problem too, because writes start
    failing everywhere; the probe exists to catch exactly that, so a full host cannot read green."""
    home = _healthy_home(tmp_path)
    _fake_disk_usage(home, 100)
    _fake_own_usage(home, 300)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "100%" in run.stdout
    # Pins the escalation, since the own-usage RED would also fire on a returncode check alone.
    assert "tell the user tonight" in run.stdout


def test_a_full_host_disk_reports_even_when_this_agent_is_also_over(tmp_path):
    """The two facts are independent, so a large own footprint must not swallow the host reading:
    the night both are true is the night the host figure matters most."""
    home = _healthy_home(tmp_path)
    _fake_disk_usage(home, 99)
    _fake_own_usage(home, 25_000)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED disk at 99% and this agent holds 25000MB" in run.stdout
    assert "RED host disk at 99%" in run.stdout


def _fake_du_timeout(home: pl.Path) -> None:
    # The walk is bounded by `timeout`, so a pathological tree or a stuck filesystem cannot hang
    # the dream; the shim stands in for the bound firing (exit 124) without waiting it out.
    fake_timeout = home / "bin" / "timeout"
    fake_timeout.write_text("#!/bin/sh\nexit 124\n")
    fake_timeout.chmod(0o755)


def test_a_du_walk_that_never_finishes_on_a_healthy_disk_stays_green(tmp_path):
    # df is the disk-full signal; du only sizes this agent's share, and a slow walk over a large
    # tree on a busy host says nothing about disk health. The share is reported as unmeasured, not 0.
    home = _healthy_home(tmp_path)
    _fake_du_timeout(home)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "footprint unmeasured, disk at 42%" in run.stdout
    assert "0MB" not in run.stdout


def test_a_du_walk_that_never_finishes_on_a_full_disk_goes_red(tmp_path):
    home = _healthy_home(tmp_path)
    _fake_disk_usage(home, 90)
    _fake_du_timeout(home)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED sizing" in run.stdout
    assert "0MB" not in run.stdout


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
    written = summary / "2026-01-01T0300.md"
    written.write_text("summary")
    aged = time.time() - hours_old * 3600
    os.utime(written, (aged, aged))
    return written


def test_a_recent_dreamer_summary_stays_green(tmp_path):
    home = _healthy_home(tmp_path)
    _dreamer_summary(home, 17)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "cadence intact" in run.stdout


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
    assert "RED no dreamer summary written in 30h: a night was missed" in run.stdout


def test_a_box_that_has_never_dreamed_stays_green(tmp_path):
    """A fresh box has no summaries at all, and a probe that reads that as a missed night is red
    from birth with nothing the agent can do about it."""
    run = _run(_healthy_home(tmp_path))

    assert run.returncode == 0, run.stdout + run.stderr
    assert "no dreamer summaries yet" in run.stdout
