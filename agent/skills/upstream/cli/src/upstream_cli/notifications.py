"""The notification files this skill writes into the agent's intake."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

SOURCE = "upstream"
NOTIFICATIONS_DIR = Path.home() / "agent" / "notifications"


def write_notification(notif_dir: Path, notif_type: str, **fields: object) -> Path:
    """One `<time_ns>-upstream-<type>.json`, renamed into place so the agent never reads a partial file."""
    notif_dir.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": SOURCE,
        "type": notif_type,
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
        **fields,
    }
    path = notif_dir / f"{time.time_ns()}-{SOURCE}-{notif_type}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(notif))
    tmp.replace(path)
    return path
