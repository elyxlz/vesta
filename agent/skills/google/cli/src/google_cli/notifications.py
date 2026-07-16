import json
import time
from datetime import UTC, datetime
from pathlib import Path


def write_notification(notif_dir: Path, notif_type: str, **fields) -> None:
    notif_dir.mkdir(exist_ok=True)
    notif = {
        "source": "google",
        "type": notif_type,
        **{k: v for k, v in fields.items() if v is not None},
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    filename = f"{int(time.time() * 1e6)}-google-{notif_type}.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    tmp.replace(notif_dir / filename)
