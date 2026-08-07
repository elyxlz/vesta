"""Boot's daemon-record clearing (claude_runtime._clear_daemon_records)."""

import pathlib as pl

from core.claude_runtime import _clear_daemon_records


def test_boot_clears_pid_and_port_records_but_spares_health(tmp_path: pl.Path):
    """A pid record is meaningless in the fresh container's pid space, so boot empties it. A
    health record describes the daemon's work against its upstream, which a restart does not
    reset, and its persisted notified-state is what keeps a restart from re-announcing a failure
    the agent was already told about; clearing it would re-announce a long-broken credential on
    every reboot."""
    daemons = tmp_path / "daemons"
    daemons.mkdir()
    (daemons / "finance.pid").write_text("123 456")
    (daemons / "tasks.port").write_text("8123")
    (daemons / "finance.health").write_text('{"healthy": false}')
    kept_dir = daemons / "someone-elses-directory"
    kept_dir.mkdir()

    _clear_daemon_records(daemons)

    assert sorted(path.name for path in daemons.iterdir()) == ["finance.health", "someone-elses-directory"]


def test_a_missing_records_dir_is_a_no_op(tmp_path: pl.Path):
    _clear_daemon_records(tmp_path / "absent")
