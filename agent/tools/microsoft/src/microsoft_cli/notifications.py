import json
import os
import time
from datetime import datetime, UTC
from pathlib import Path


def write_notification(notif_dir: Path, type: str, **fields):
    notif_dir.mkdir(exist_ok=True)

    notif = {
        "source": "microsoft",
        "type": type,
        **{k: v for k, v in fields.items() if v is not None},
        "timestamp": datetime.now(UTC).isoformat(),
    }

    filename = f"{int(time.time() * 1e6)}-microsoft-{type}.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    os.replace(tmp, notif_dir / filename)
