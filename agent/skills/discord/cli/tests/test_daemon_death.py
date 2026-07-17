"""When the gateway daemon exits, it writes a daemon_died notification the agent restarts from."""

import json
import pathlib

from discord_cli.notif import daemon_died_notification, write_notification


def test_daemon_died_notification_shape():
    notif = daemon_died_notification()
    assert notif["source"] == "discord"
    assert notif["type"] == "daemon_died"
    # No interrupt=False, so the model's default (interrupt) applies: a dead channel preempts.
    assert "interrupt" not in notif


def test_death_notification_is_written_to_disk(tmp_path: pathlib.Path):
    path = write_notification(tmp_path, daemon_died_notification())
    assert path.parent == tmp_path
    written = json.loads(path.read_text())
    assert written["source"] == "discord"
    assert written["type"] == "daemon_died"
