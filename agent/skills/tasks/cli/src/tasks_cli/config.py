from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    """The production tasks store, and the single owner of this path (the db migration guard reads it too)."""
    return Path.home() / ".tasks"


@dataclass
class Config:
    data_dir: Path = field(default_factory=default_data_dir)
    log_dir: Path = field(default_factory=lambda: default_data_dir() / "logs")
    monitor_interval: int = 60
