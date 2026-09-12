from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    return Path.home() / ".flashcards"


@dataclass
class Config:
    data_dir: Path = field(default_factory=default_data_dir)
    log_dir: Path = field(default_factory=lambda: default_data_dir() / "logs")
