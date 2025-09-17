"""Write notifications to Vesta's directory"""

import json
import time
from datetime import datetime
from pathlib import Path

NOTIF_DIR = Path("notifications")


def write_notification(type: str, message: str, metadata: dict):
    NOTIF_DIR.mkdir(exist_ok=True)

    notif = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "microsoft",
        "type": type,
        "message": message,
        "metadata": metadata,
    }

    filename = f"{int(time.time() * 1e6)}-microsoft-{type}.json"
    (NOTIF_DIR / filename).write_text(json.dumps(notif, indent=2))
