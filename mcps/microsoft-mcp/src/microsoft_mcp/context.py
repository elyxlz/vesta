import httpx
import logging
import threading
from pathlib import Path
from dataclasses import dataclass
from .settings import MicrosoftSettings


@dataclass
class MicrosoftContext:
    cache_file: Path
    http_client: httpx.Client
    log_dir: Path
    notif_dir: Path
    monitor_base_dir: Path
    monitor_state_file: Path
    monitor_log_file: Path
    monitor_logger: logging.Logger
    monitor_stop_event: threading.Event
    scopes: list[str]
    base_url: str
    upload_chunk_size: int
    folders: dict[str, str]
    settings: MicrosoftSettings
    # Calendar notification thresholds in minutes (default: 1 week, 1 hour, 15 mins)
    calendar_notify_thresholds: list[int] | None = None

    def get_calendar_notify_thresholds(self) -> list[int]:
        return self.calendar_notify_thresholds or [10080, 60, 15]  # 1 week, 1 hour, 15 mins
