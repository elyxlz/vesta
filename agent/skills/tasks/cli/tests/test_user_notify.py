"""The agent's own task activity surfaces to the app clients as a `task` user notification.

`create` and completion (`done`, or `update --status completed`) fire the vestad
user-notification helper, fire-and-forget; other commands stay silent.
"""

import pytest
from tasks_cli import cli, commands
from tasks_cli.config import Config


@pytest.fixture
def sent(monkeypatch) -> list[list[str]]:
    monkeypatch.setenv("AGENT_NAME", "scout")
    calls: list[list[str]] = []

    class _Proc:
        pass

    def fake_popen(argv, **_kwargs):
        calls.append(list(argv))
        return _Proc()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    return calls


def _run(tmp_config: Config, argv: list[str]) -> None:
    args = cli._build_parser().parse_args(argv)
    cli._handle_task(args, tmp_config)


def test_create_notifies_a_task_kind(tmp_config: Config, sent: list[list[str]]):
    _run(tmp_config, ["create", "buy milk"])
    assert sent == [["user-notification", "task", "scout added a task: buy milk"]]


def test_done_notifies_a_task_kind(tmp_config: Config, sent: list[list[str]]):
    task = commands.add_task(tmp_config, subject="call the dentist")
    _run(tmp_config, ["done", task["id"]])
    assert sent == [["user-notification", "task", "scout completed a task: call the dentist"]]


def test_update_to_completed_notifies_but_other_updates_stay_silent(tmp_config: Config, sent: list[list[str]]):
    task = commands.add_task(tmp_config, subject="water the plants")
    _run(tmp_config, ["update", task["id"], "--priority", "high"])
    assert sent == []
    _run(tmp_config, ["update", task["id"], "--status", "completed"])
    assert sent == [["user-notification", "task", "scout completed a task: water the plants"]]
