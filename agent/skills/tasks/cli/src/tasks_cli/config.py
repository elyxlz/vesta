from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    data_dir: Path = Path.home() / ".tasks"
    log_dir: Path = Path.home() / ".tasks" / "logs"
    monitor_interval: int = 60
