"""When the voice-server exits, it writes a daemon_died notification the agent restarts from."""

import json
from pathlib import Path

from voice.server import write_daemon_died


def test_write_daemon_died_writes_notification(tmp_path: Path):
    write_daemon_died(tmp_path)
    files = list(tmp_path.glob("*-voice-daemon_died.json"))
    assert len(files) == 1
    notif = json.loads(files[0].read_text())
    assert notif["source"] == "voice"
    assert notif["type"] == "daemon_died"


def test_write_daemon_died_creates_missing_dir(tmp_path: Path):
    target = tmp_path / "notifications"
    write_daemon_died(target)
    assert list(target.glob("*-voice-daemon_died.json"))
