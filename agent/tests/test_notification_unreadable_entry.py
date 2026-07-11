"""Prove that a directory named *.json inside notifications_dir kills load_notifications.

The bug: _load_notification_files calls f.read_text() inside a list comprehension with no
error handling.  load_notifications only catches json/pydantic parse errors, not OSError.
A directory entry named foo.json raises IsADirectoryError, which propagates uncaught.
The correct behavior is that the bad entry is skipped and an empty list is returned.
"""

import pytest
import core.config as cfg
from core.loops import load_notifications


@pytest.mark.anyio
async def test_directory_named_dot_json_is_skipped_not_fatal(tmp_path):
    """A *.json directory entry should be skipped; load_notifications must not raise."""
    agent_dir = tmp_path / "agent"
    notifs_dir = agent_dir / "notifications"
    notifs_dir.mkdir(parents=True)

    # Create a directory (not a file) named foo.json — reproduced exactly as described.
    bad_entry = notifs_dir / "foo.json"
    bad_entry.mkdir()

    config = cfg.VestaConfig(agent_dir=agent_dir)

    # Bug: raises IsADirectoryError instead of returning [] and skipping the bad entry.
    result = await load_notifications(config=config)
    assert result == []
