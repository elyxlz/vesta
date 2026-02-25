import json
import time
from datetime import datetime, UTC
from pathlib import Path


def write_notification(notif_dir: Path, type: str, **fields):
    notif_dir.mkdir(exist_ok=True)

    notif = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "microsoft",
        "type": type,
        **{k: v for k, v in fields.items() if v is not None},
    }

    filename = f"{int(time.time() * 1e6)}-microsoft-{type}.json"
    (notif_dir / filename).write_text(json.dumps(notif, indent=2))
