"""Write notifications to Vesta's directory"""

import json
import time
from pathlib import Path

NOTIF_DIR = Path("notifications")


def write_notification(type: str, data: dict):
    NOTIF_DIR.mkdir(exist_ok=True)

    notif = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "microsoft",
        "type": type,
        "data": data,
    }

    filename = f"{int(time.time() * 1e6)}-microsoft-{type}.json"
    (NOTIF_DIR / filename).write_text(json.dumps(notif, indent=2))
