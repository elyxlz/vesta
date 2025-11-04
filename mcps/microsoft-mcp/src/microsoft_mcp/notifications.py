import json
import time
from datetime import datetime, timezone
from pathlib import Path

_notif_dir: Path | None = None


def init_notifications(notif_dir: Path):
    global _notif_dir
    _notif_dir = notif_dir


def write_notification(type: str, message: str, metadata: dict):
    assert _notif_dir
    _notif_dir.mkdir(exist_ok=True)

    notif = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "microsoft",
        "type": type,
        "message": message,
        "metadata": metadata,
    }

    filename = f"{int(time.time() * 1e6)}-microsoft-{type}.json"
    (_notif_dir / filename).write_text(json.dumps(notif, indent=2))
