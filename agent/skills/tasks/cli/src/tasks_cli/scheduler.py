"""Notification writing for the tasks daemon."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path


def write_notification(notif_dir: Path, type_: str, **fields: object) -> None:
    """Atomically write a `source=tasks` notification JSON file. Single owner of the
    on-disk notification format (source, timestamp, filename pattern, tmp+rename)."""
    notif_dir.mkdir(exist_ok=True)
    notif = {
        "source": "tasks",
        "type": type_,
        **fields,
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    filename = f"{int(time.time() * 1e6)}-tasks-{type_}.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    tmp.replace(notif_dir / filename)
