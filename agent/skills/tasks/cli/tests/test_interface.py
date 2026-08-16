"""Unit tests for the agent-facing interface: one time vocabulary across commands, working
--help on remind subcommands, snooze's two timing forms with the old-to-new echo, and bare
times for daily reminders."""

import json
import sys
from datetime import UTC, datetime, timedelta

import pytest
from tasks_cli import cli, commands, db
from tasks_cli.config import Config


def _run_cli(monkeypatch, capsys, cfg: Config, *argv: str) -> tuple[str, str]:
    monkeypatch.setattr(cli, "Config", lambda: cfg)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["tasks", *argv])
    cli.main()
    captured = capsys.readouterr()
    return captured.out, captured.err


# ---------------------------------------------------------------------------
# One time vocabulary
# ---------------------------------------------------------------------------


def test_create_accepts_at_and_tz(tmp_config: Config, monkeypatch, capsys):
    out, _ = _run_cli(monkeypatch, capsys, tmp_config, "create", "meet", "--at", "2027-01-01T10:00:00", "--tz", "UTC")
    task = json.loads(out)
    assert db.parse_datetime(task["due_date"]) == datetime(2027, 1, 1, 10, tzinfo=UTC)


def test_create_accepts_in_hours(tmp_config: Config, monkeypatch, capsys):
    out, _ = _run_cli(monkeypatch, capsys, tmp_config, "create", "soon", "--in-hours", "4")
    task = json.loads(out)
    delta = db.parse_datetime(task["due_date"]) - datetime.now(UTC)
    assert timedelta(hours=3, minutes=55) < delta < timedelta(hours=4, minutes=5)


def test_create_still_accepts_the_due_spellings(tmp_config: Config, monkeypatch, capsys):
    out, _ = _run_cli(monkeypatch, capsys, tmp_config, "create", "meet", "--due-datetime", "2027-01-01T10:00:00", "--timezone", "UTC")
    assert db.parse_datetime(json.loads(out)["due_date"]) == datetime(2027, 1, 1, 10, tzinfo=UTC)


def test_update_accepts_at_and_tz(tmp_config: Config, monkeypatch, capsys):
    task = commands.add_task(tmp_config, subject="movable")
    out, _ = _run_cli(monkeypatch, capsys, tmp_config, "update", task["id"], "--at", "2027-02-01T09:00:00", "--tz", "UTC")
    assert db.parse_datetime(json.loads(out)["due_date"]) == datetime(2027, 2, 1, 9, tzinfo=UTC)


# ---------------------------------------------------------------------------
# --help teaches instead of erroring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcommand", ["list", "snooze", "delete", "update"])
def test_remind_subcommand_help_exits_zero_and_prints_usage(tmp_config: Config, monkeypatch, capsys, subcommand: str):
    monkeypatch.setattr(cli, "Config", lambda: tmp_config)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["tasks", "remind", subcommand, "--help"])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 0
    assert f"usage: tasks remind {subcommand}" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Snooze: two timing forms, old-to-new echo
# ---------------------------------------------------------------------------


def test_snooze_result_echoes_previous_and_next_run(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="m", in_hours=1))
    result = commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(in_hours=4))
    assert result["previous_run"] == reminder["next_run"]
    assert db.parse_datetime(result["next_run"]) > db.parse_datetime(result["previous_run"])


def test_snooze_rejects_mixed_timing_forms(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="m", in_hours=1))
    with pytest.raises(ValueError, match="Pick one"):
        commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(in_hours=2, at="2026-12-01T10:00:00", tz="UTC"))


# ---------------------------------------------------------------------------
# Bare times for daily reminders
# ---------------------------------------------------------------------------


def test_daily_reminder_accepts_a_bare_time(tmp_config: Config):
    result = commands.remind_set(
        tmp_config, commands.ReminderSpec(message="wind down", recurring="daily", scheduled_datetime="21:30", tz="Europe/Rome")
    )
    assert result["schedule"] == "daily at 21:30 Europe/Rome"


def test_weekly_reminder_still_requires_a_date(tmp_config: Config):
    """A weekly schedule takes its weekday from the date, so a bare time carries too little."""
    with pytest.raises(ValueError):
        commands.remind_set(tmp_config, commands.ReminderSpec(message="weekly", recurring="weekly", scheduled_datetime="09:00", tz="UTC"))
