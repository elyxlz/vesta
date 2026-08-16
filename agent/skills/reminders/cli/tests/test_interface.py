"""Unit tests for the agent-facing interface: working --help on reminders subcommands, snooze's two
timing forms with the old-to-new echo, bare times for daily reminders, and local-offset echoes."""

import sys

import pytest
from reminders_cli import cli, commands, db
from reminders_cli.config import Config


@pytest.fixture
def rome_process_tz(monkeypatch):
    """The agent's own zone is Europe/Rome: the TZ env var every command reads and echoes with."""
    monkeypatch.setenv("TZ", "Europe/Rome")


# ---------------------------------------------------------------------------
# --help teaches instead of erroring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcommand", ["list", "snooze", "delete", "update"])
def test_remind_subcommand_help_exits_zero_and_prints_usage(tmp_config: Config, monkeypatch, capsys, subcommand: str):
    monkeypatch.setattr(cli, "Config", lambda: tmp_config)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["reminders", subcommand, "--help"])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 0
    assert f"usage: reminders {subcommand}" in capsys.readouterr().out


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


def test_daily_reminder_accepts_a_bare_time(tmp_config: Config, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Rome")
    result = commands.remind_set(tmp_config, commands.ReminderSpec(message="wind down", recurring="daily", scheduled_datetime="21:30"))
    assert result["schedule"] == "daily at 21:30"


def test_daily_reminder_bare_time_with_tz_keeps_the_pinned_zone_in_the_label(tmp_config: Config):
    result = commands.remind_set(
        tmp_config, commands.ReminderSpec(message="wind down", recurring="daily", scheduled_datetime="21:30", tz="Europe/Rome")
    )
    assert result["schedule"] == "daily at 21:30 Europe/Rome"


def test_weekly_reminder_still_requires_a_date(tmp_config: Config):
    """A weekly schedule takes its weekday from the date, so a bare time carries too little."""
    with pytest.raises(ValueError):
        commands.remind_set(tmp_config, commands.ReminderSpec(message="weekly", recurring="weekly", scheduled_datetime="09:00"))


# ---------------------------------------------------------------------------
# Echoed instants render with the local offset; storage stays UTC
# ---------------------------------------------------------------------------


def test_one_shot_echoes_next_run_with_the_local_offset(tmp_config: Config, rome_process_tz):
    result = commands.remind_set(tmp_config, commands.ReminderSpec(message="call", scheduled_datetime="2026-12-01T09:00:00"))
    assert result["next_run"] == "2026-12-01T09:00:00+01:00"


def test_snooze_at_without_tz_resolves_local_and_echoes_local(tmp_config: Config, rome_process_tz):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="m", in_hours=1))
    result = commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(at="2026-12-01T17:00:00"))
    assert result["next_run"] == "2026-12-01T17:00:00+01:00"
    assert db.parse_datetime(result["previous_run"]) == db.parse_datetime(reminder["next_run"])
