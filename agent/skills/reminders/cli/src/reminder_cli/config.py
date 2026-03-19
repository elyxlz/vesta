from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    data_dir: Path = Path.home() / ".reminder"
    log_dir: Path = Path.home() / ".reminder" / "logs"
