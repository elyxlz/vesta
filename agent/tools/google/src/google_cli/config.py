from dataclasses import dataclass, field
from pathlib import Path

VESTA_DIR = Path.home()

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]
MEET_SCOPES = [
    "https://www.googleapis.com/auth/meetings.space.created",
]
SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES + MEET_SCOPES


@dataclass
class Config:
    data_dir: Path = VESTA_DIR / "data" / "google"
    log_dir: Path = VESTA_DIR / "logs" / "google"
    notif_dir: Path = VESTA_DIR / "notifications"
    scopes: list[str] = field(default_factory=lambda: list(SCOPES))
    calendar_notify_thresholds: list[int] | None = None

    @property
    def credentials_file(self) -> Path:
        return self.data_dir / "credentials.json"

    @property
    def token_file(self) -> Path:
        return self.data_dir / "token.json"

    def get_calendar_notify_thresholds(self) -> list[int]:
        return self.calendar_notify_thresholds or [10080, 60, 15]
