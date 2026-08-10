"""Completing a task through the app notifies the agent; the agent's own CLI completions do not.

The reminder fire path never checks task status, and the agent only learns of app-side edits it did
not make, so a pending->done transition through the HTTP handler writes a snoozed `task_completed`
notification. A completion through `commands.update_task` (the agent's own CLI) writes nothing.
"""

import json
from pathlib import Path

from tasks_cli import commands, server
from tasks_cli.config import Config


def _completion_notifs(notif_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in notif_dir.glob("*-tasks-task_completed.json")]


def test_app_completion_writes_a_snoozed_notification(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    task = commands.add_task(tmp_config, subject="call the dentist")

    server._apply_task_update(tmp_config, notif_dir, task["id"], server.UpdateTaskBody(status="completed"))

    notifs = _completion_notifs(notif_dir)
    assert len(notifs) == 1
    assert notifs[0]["interrupt"] is False, "a completion is informational, so it must snooze, not interrupt"
    assert notifs[0]["task_id"] == task["id"]
    assert "call the dentist" in notifs[0]["message"]


def test_app_completion_notifies_once_not_on_a_repeat(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    task = commands.add_task(tmp_config, subject="x")

    server._apply_task_update(tmp_config, notif_dir, task["id"], server.UpdateTaskBody(status="completed"))
    server._apply_task_update(tmp_config, notif_dir, task["id"], server.UpdateTaskBody(status="completed"))

    assert len(_completion_notifs(notif_dir)) == 1, "re-sending done on an already-done task must not re-notify"


def test_app_edit_that_is_not_a_completion_does_not_notify(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    task = commands.add_task(tmp_config, subject="x")

    server._apply_task_update(tmp_config, notif_dir, task["id"], server.UpdateTaskBody(subject="renamed"))

    assert _completion_notifs(notif_dir) == []


def test_cli_completion_does_not_notify(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    task = commands.add_task(tmp_config, subject="x")

    commands.update_task(tmp_config, task_id=task["id"], status="completed")

    assert _completion_notifs(notif_dir) == [], "the agent's own CLI completion is self-evident and must stay silent"
