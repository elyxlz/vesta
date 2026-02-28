import json
import os
import time
from datetime import datetime, UTC
from pathlib import Path


def write_notification(notif_dir: Path, type: str, **fields) -> None:
    notif_dir.mkdir(exist_ok=True)
    notif = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "google",
        "type": type,
        **{k: v for k, v in fields.items() if v is not None},
    }
    filename = f"{int(time.time() * 1e6)}-google-{type}.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    os.replace(tmp, notif_dir / filename)
