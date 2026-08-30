"""The dream's reality check probes the running system, not the dream's own record."""

import os
import pathlib as pl
import shutil
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
    (tmp_path / "agent" / "dreamer").mkdir(parents=True)
    (tmp_path / "agent" / "dreamer" / "2026-01-01T0300.md").write_text("stub")
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


_STALE = 1_000_000_000  # far past the 24h freshness window


def test_running_daemon_with_a_stale_log_goes_red(tmp_path):
    # The gap this closes is silent by construction: the error-storm loop skips logs untouched for
    # 24h, so a live daemon whose logging has broken produces no line at all rather than a RED, and
    # an absent check is indistinguishable from one fewer thing to check.
    home = _healthy_home(tmp_path)
    (home / "agent" / "data" / "daemons" / "mute.pid").write_text(f"{os.getpid()} 12345")
    log = home / "agent" / "logs" / "mute.log"
    log.write_text("INFO fine\n")
    os.utime(log, (_STALE, _STALE))

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED daemon mute is running but mute.log has not been written in over 24h" in run.stdout


def test_running_daemon_with_a_fresh_log_stays_green(tmp_path):
    # The healthy direction: a cross-reference that cannot stay quiet turns every live daemon RED.
    home = _healthy_home(tmp_path)
    (home / "agent" / "data" / "daemons" / "chatty.pid").write_text(f"{os.getpid()} 12345")
    (home / "agent" / "logs" / "chatty.log").write_text("INFO fine\n")

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK  daemon chatty is running" in run.stdout


def test_dead_daemon_with_a_stale_log_is_only_reported_once(tmp_path):
    # A dead daemon's log is stale too. It belongs to the died-and-nothing-restarted-it branch, and
    # reporting it twice would train the reader to skim the daemon section.
    home = _healthy_home(tmp_path)
    (home / "agent" / "data" / "daemons" / "ghost.pid").write_text("99999999 12345")
    log = home / "agent" / "logs" / "ghost.log"
    log.write_text("INFO fine\n")
    os.utime(log, (_STALE, _STALE))

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED daemon ghost has a record but no process" in run.stdout
    assert "has not been written in over 24h" not in run.stdout


def test_error_storm_in_a_recent_log_goes_red(tmp_path):
    # The RED must survive the loop: a counter incremented in a pipeline subshell is lost by the
    # time the exit code is computed, which turns a red probe into a green exit.
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "stormy.log").write_text("ERROR boom\n" * 300)

    run = _run(home)

    assert run.returncode == 1
    assert "RED stormy.log" in run.stdout


def test_error_storm_survives_nul_bytes_in_the_log(tmp_path):
    # Logs acquire NUL bytes from an unclean write, and grep then reads the stream as binary. The
    # storm has to be counted anyway: a log that has just been truncated by a crash is exactly the
    # log worth reading.
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "truncated.log").write_bytes(b"INFO fine\n" * 10 + b"\x00" * 200 + b"\nERROR boom\n" * 300)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED truncated.log" in run.stdout


def test_an_uncomputable_error_count_goes_red(tmp_path):
    # The failure this guards is silent by construction: the count comes back empty, the arithmetic
    # test errors on it, and the else branch reports the log as healthy. A probe that has stopped
    # working must say so rather than pass. The shim stands in for any grep that writes nothing for
    # a stream it considers binary.
    home = _healthy_home(tmp_path)
    (home / "agent" / "logs" / "some.log").write_text("ERROR boom\n" * 300)
    fake_grep = home / "bin" / "grep"
    fake_grep.write_text("#!/bin/sh\nexit 1\n")
    fake_grep.chmod(0o755)

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "RED some.log" in run.stdout
    assert "the probe itself is broken" in run.stdout


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


def test_a_fresh_dreamer_summary_stays_green(tmp_path):
    # The healthy case for this probe: a summary written last night is the normal state, and the
    # probe has to be able to say so. A check that only ever fires is not a check.
    home = _healthy_home(tmp_path)

    run = _run(home)

    assert run.returncode == 0, run.stdout + run.stderr
    assert "dreamer summary written within 48h" in run.stdout


def test_a_stale_dreamer_summary_goes_red(tmp_path):
    # A dream can do its work, update memory, mark itself complete, and never write its record. The
    # retrospective reads this directory, so the NEXT dream then reads stale history with no sign
    # that a night is missing. Nothing else in the probe would notice: an absent summary looks
    # exactly like a night that did not need one.
    home = _healthy_home(tmp_path)
    old = home / "agent" / "dreamer" / "2026-01-01T0300.md"
    stale = time.time() - 5 * 24 * 3600
    os.utime(old, (stale, stale))

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "over 48h old" in run.stdout


def test_an_empty_dreamer_directory_goes_red(tmp_path):
    home = _healthy_home(tmp_path)
    (home / "agent" / "dreamer" / "2026-01-01T0300.md").unlink()

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "dreamer directory is empty" in run.stdout


def test_a_missing_dreamer_directory_goes_red(tmp_path):
    home = _healthy_home(tmp_path)
    shutil.rmtree(home / "agent" / "dreamer")

    run = _run(home)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "no dreamer directory" in run.stdout
