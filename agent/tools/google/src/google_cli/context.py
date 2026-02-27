import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import Config


@dataclass
class GoogleContext:
    config: Config

    monitor_base_dir: Path
    monitor_state_file: Path
    monitor_log_file: Path
    monitor_logger: logging.Logger
    monitor_stop_event: threading.Event
