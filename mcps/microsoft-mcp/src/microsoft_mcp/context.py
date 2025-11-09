import httpx
import logging
import threading
from pathlib import Path
from dataclasses import dataclass


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
