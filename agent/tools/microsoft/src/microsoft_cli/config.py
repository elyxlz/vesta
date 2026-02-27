from dataclasses import dataclass, field
from pathlib import Path

VESTA_DIR = Path.home()

SCOPES = ["https://graph.microsoft.com/.default"]
BASE_URL = "https://graph.microsoft.com/v1.0"
UPLOAD_CHUNK_SIZE = 15 * 320 * 1024

FOLDERS = {
    "inbox": "inbox",
    "sent": "sentitems",
    "drafts": "drafts",
    "deleted": "deleteditems",
    "junk": "junkemail",
    "archive": "archive",
}


@dataclass
class Config:
    data_dir: Path = VESTA_DIR / "data" / "microsoft"
    log_dir: Path = VESTA_DIR / "logs" / "microsoft"
    notif_dir: Path = VESTA_DIR / "notifications"
    scopes: list[str] = field(default_factory=lambda: list(SCOPES))
    base_url: str = BASE_URL
    upload_chunk_size: int = UPLOAD_CHUNK_SIZE
    folders: dict[str, str] = field(default_factory=lambda: dict(FOLDERS))
    calendar_notify_thresholds: list[int] | None = None

    @property
    def cache_file(self) -> Path:
        return self.data_dir / "auth_cache.bin"

    def get_calendar_notify_thresholds(self) -> list[int]:
        return self.calendar_notify_thresholds or [10080, 60, 15]
