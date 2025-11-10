import json
import time
from datetime import datetime, timezone
from pathlib import Path


def write_notification(notif_dir: Path, type: str, message: str, metadata: dict):
    notif_dir.mkdir(exist_ok=True)

    notif = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "microsoft",
        "type": type,
        "message": message,
        "metadata": metadata,
    }

    filename = f"{int(time.time() * 1e6)}-microsoft-{type}.json"
    (notif_dir / filename).write_text(json.dumps(notif, indent=2))
