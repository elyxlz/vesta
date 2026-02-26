import json
import time
from datetime import datetime, UTC
from pathlib import Path


def write_notification(notif_dir: Path, type: str, **fields) -> None:
    notif = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "google",
        "type": type,
        **{k: v for k, v in fields.items() if v is not None},
    }
    filename = f"{int(time.time() * 1e6)}-google-{type}.json"
    (notif_dir / filename).write_text(json.dumps(notif, indent=2))
