import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

NOTIF_DIR = Path(os.environ.get("NOTIFICATIONS_DIR", "../../notifications")).resolve()


def write_notification(type: str, message: str, metadata: dict):
    NOTIF_DIR.mkdir(exist_ok=True)

    notif = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "microsoft",
        "type": type,
        "message": message,
        "metadata": metadata,
    }

    filename = f"{int(time.time() * 1e6)}-microsoft-{type}.json"
    (NOTIF_DIR / filename).write_text(json.dumps(notif, indent=2))
