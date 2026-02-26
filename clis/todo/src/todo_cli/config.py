from dataclasses import dataclass
from pathlib import Path

VESTA_DIR = Path.home()


@dataclass
class Config:
    data_dir: Path = VESTA_DIR / "data" / "todo"
    log_dir: Path = VESTA_DIR / "logs" / "todo"
    notif_dir: Path = VESTA_DIR / "notifications"
    monitor_interval: int = 60
