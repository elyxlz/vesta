from dataclasses import dataclass, field
from pathlib import Path


# mail.google.com is the full-Gmail scope (a superset the Gmail REST API accepts,
# covering everything gmail.modify + gmail.send did). It rides the same verified
# Thunderbird consent screen as calendar, so one sign-in grants both. Using the
# full scope keeps the default sign-in to a single verified consent screen.
GMAIL_SCOPES = [
    "https://mail.google.com/",
]
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]
# Documented constant only — NOT wired into any command. Google Meet cannot work
# under the reused Thunderbird client: the standalone Meet API needs this
# "restricted" scope the client is not verified for, and the calendar
# conferenceData path needs the Calendar REST API, which is disabled on that
# client's Cloud project. Kept here purely as a reference for a future own-app
# (credentials.json) integration; the `meet` command has been removed.
MEET_SCOPE = "https://www.googleapis.com/auth/meetings.space.created"
SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES


@dataclass
class Config:
    data_dir: Path = Path.home() / ".google"
    log_dir: Path = Path.home() / ".google" / "logs"
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
