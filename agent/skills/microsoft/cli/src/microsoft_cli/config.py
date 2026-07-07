from dataclasses import dataclass, field
from pathlib import Path

from .settings import get_settings, DEFAULT_CLIENT_ID

# Dynamic-consent scopes for the shared default public client (it has no permissions we control,
# so ".default" would either grant nothing useful or demand admin consent for its whole catalog).
DEFAULT_CLIENT_SCOPES = [
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Mail.Send",
    "https://graph.microsoft.com/Calendars.ReadWrite",
    "https://graph.microsoft.com/MailboxSettings.ReadWrite",
]
# A user's own app registration: request exactly the delegated permissions it was configured with.
OWNED_APP_SCOPES = ["https://graph.microsoft.com/.default"]


def resolve_scopes() -> list[str]:
    return list(DEFAULT_CLIENT_SCOPES) if get_settings().microsoft_mcp_client_id == DEFAULT_CLIENT_ID else list(OWNED_APP_SCOPES)


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
    data_dir: Path = Path.home() / ".microsoft"
    log_dir: Path = Path.home() / ".microsoft" / "logs"
    scopes: list[str] = field(default_factory=resolve_scopes)
    base_url: str = BASE_URL
    upload_chunk_size: int = UPLOAD_CHUNK_SIZE
    folders: dict[str, str] = field(default_factory=lambda: dict(FOLDERS))
    calendar_notify_thresholds: list[int] | None = None

    @property
    def cache_file(self) -> Path:
        return self.data_dir / "auth_cache.bin"
