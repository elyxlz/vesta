"""`tasks remind list --json` never silently truncates: JSON is consumed by scripts asking absence
questions ("is anything scheduled for X?"), so a hidden page size would answer them wrongly. Only an
explicit --limit caps JSON output; the human table keeps its page size."""

import json
import sys
from pathlib import Path

import pytest
from tasks_cli import cli, commands, db
from tasks_cli.config import Config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    cfg = Config(data_dir=tmp_path / "tasks", log_dir=tmp_path / "tasks" / "logs")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(cfg.data_dir)
    return cfg


REMINDER_COUNT = 60  # comfortably past the table page size of 50


def _seed_reminders(cfg: Config, count: int) -> None:
    for i in range(count):
        commands.remind_set(cfg, commands.ReminderSpec(message=f"r{i}", in_minutes=10 + i))


def _run_remind_list(monkeypatch, capsys, cfg: Config, *argv: str) -> str:
    monkeypatch.setattr(cli, "Config", lambda: cfg)
    monkeypatch.setattr(cli.daemon, "live_pid", lambda: 1)
    monkeypatch.setattr(sys, "argv", ["tasks", "remind", "list", *argv])
    cli.main()
    return capsys.readouterr().out


@pytest.mark.parametrize("json_flag", ["--json", "--json-pretty"])
def test_json_returns_every_reminder(tmp_config: Config, monkeypatch, capsys, json_flag: str):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    listed = json.loads(_run_remind_list(monkeypatch, capsys, tmp_config, json_flag))
    assert len(listed) == REMINDER_COUNT


def test_json_honors_an_explicit_limit(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    listed = json.loads(_run_remind_list(monkeypatch, capsys, tmp_config, "--json", "--limit", "10"))
    assert len(listed) == 10


def test_table_output_keeps_its_page_size(tmp_config: Config, monkeypatch, capsys):
    _seed_reminders(tmp_config, REMINDER_COUNT)
    lines = _run_remind_list(monkeypatch, capsys, tmp_config).strip().splitlines()
    assert lines[0].startswith("NOTE:")
    assert len(lines[1:]) == cli.REMIND_LIST_PAGE_SIZE


def test_a_cut_table_says_so(tmp_config: Config, monkeypatch, capsys):
    """A capped page that ends silently is indistinguishable from a complete one, and gets read as
    the whole list. The table answers absence questions as often as the JSON does."""
    _seed_reminders(tmp_config, REMINDER_COUNT)
    out = _run_remind_list(monkeypatch, capsys, tmp_config, "--limit", "10")
    assert "truncated" in out.splitlines()[0]
    assert len(out.strip().splitlines()[1:]) == 10


def test_an_exact_fit_says_nothing(tmp_config: Config, monkeypatch, capsys):
    """The note has to be earned. Asking for one row more than is shown is what separates a page
    that was cut from a page that merely filled, so a full-but-complete list stays quiet."""
    _seed_reminders(tmp_config, cli.REMIND_LIST_PAGE_SIZE)
    lines = _run_remind_list(monkeypatch, capsys, tmp_config).strip().splitlines()
    assert not any(line.startswith("NOTE:") for line in lines)
    assert len(lines) == cli.REMIND_LIST_PAGE_SIZE


@pytest.mark.parametrize("json_flag", ["--json", "--json-pretty"])
def test_json_never_carries_the_note(tmp_config: Config, monkeypatch, capsys, json_flag: str):
    """The note is a human-table affordance; JSON is parsed, so a prose line would break it."""
    _seed_reminders(tmp_config, REMINDER_COUNT)
    out = _run_remind_list(monkeypatch, capsys, tmp_config, json_flag, "--limit", "10")
    assert "NOTE:" not in out
    assert len(json.loads(out)) == 10
