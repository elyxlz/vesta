import os
from dataclasses import dataclass
from pathlib import Path

VESTA_DIR = Path(os.environ["VESTA_ROOT"]) if "VESTA_ROOT" in os.environ else Path.home() / "vesta"


@dataclass
class Config:
    data_dir: Path = VESTA_DIR / "data" / "tasks"
    log_dir: Path = VESTA_DIR / "logs" / "tasks"
    notif_dir: Path = VESTA_DIR / "notifications"
    monitor_interval: int = 60
