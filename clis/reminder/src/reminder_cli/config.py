from dataclasses import dataclass
from pathlib import Path

VESTA_DIR = Path.home()


@dataclass
class Config:
    data_dir: Path = VESTA_DIR / "data" / "reminder"
    log_dir: Path = VESTA_DIR / "logs" / "reminder"
    notif_dir: Path = VESTA_DIR / "notifications"
