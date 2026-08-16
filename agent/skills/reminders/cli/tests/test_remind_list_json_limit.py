"""`reminders list` never silently truncates, in either format.

JSON returns every row unless --limit caps it. The human table keeps its page size but reports,
on stderr so no stdout pipe can eat it, when it held rows back."""

import json
import sys
from pathlib import Path

import pytest
from reminders_cli import cli, commands, db
from reminders_cli.config import Config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    cfg = Config(data_dir=tmp_path / "reminders", log_dir=tmp_path / "reminders" / "logs")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(cfg.data_dir)
    return cfg


REMINDER_COUNT = 60  # comfortably past the table page size of 50


def _seed_reminders(cfg: Config, count: int) -> None:
    for i in range(count):
        commands.remind_set(cfg, commands.ReminderSpec(message=f"r{i}", in_minutes=10 + i))


def _run_remind_list(monkeypatch, capsys, cfg: Config, *argv: str) -> tuple[str, str]:
    monkeypatch.setattr(cli, "Config", lambda: cfg)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["reminders", "list", *argv])
    cli.main()
    captured = capsys.readouterr()
    return captured.out, captured.err


@pytest.mark.parametrize("json_flag", ["--json", "--json-pretty"])
def test_json_returns_every_reminder(tmp_config: Config, monkeypatch, capsys, json_flag: str):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    out, _ = _run_remind_list(monkeypatch, capsys, tmp_config, json_flag)
    assert len(json.loads(out)) == REMINDER_COUNT


def test_json_honors_an_explicit_limit(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    out, _ = _run_remind_list(monkeypatch, capsys, tmp_config, "--json", "--limit", "10")
    assert len(json.loads(out)) == 10


def test_table_output_keeps_its_page_size(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    out, _ = _run_remind_list(monkeypatch, capsys, tmp_config)
    assert len(out.strip().splitlines()) == cli.REMIND_LIST_PAGE_SIZE


def test_footer_rides_stderr_so_a_stdout_pipe_cannot_eat_it(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    out, err = _run_remind_list(monkeypatch, capsys, tmp_config)
    assert "showing" not in out
    footer = err.strip()
    assert f"showing {cli.REMIND_LIST_PAGE_SIZE} of {REMINDER_COUNT}" in footer
    assert "--json" in footer, "the footer has to name a way to see the rest"


def test_table_stays_silent_when_nothing_was_held_back(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, 3)
    out, err = _run_remind_list(monkeypatch, capsys, tmp_config)
    assert len(out.strip().splitlines()) == 3
    assert err == ""


def test_an_explicit_limit_is_the_caller_asking_and_stays_silent(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    out, err = _run_remind_list(monkeypatch, capsys, tmp_config, "--limit", "5")
    assert len(out.strip().splitlines()) == 5
    assert err == ""
