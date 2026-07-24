"""Parameter shapes shared across the mail/calendar command surface.

The Graph command modules (email.py, calendar.py), their OWA REST mirrors
(owa_rest_commands.py), and the REST transport (owa_rest.py) all take the same
payloads; the CLI dispatcher builds them from parsed args. A backend that does
not support a field simply ignores it.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class MailDraft:
    """Compose surface for send / draft / forward."""

    body: str = ""
    subject: str | None = None
    to: list[str] | None = None
    cc: list[str] | None = None
    bcc: list[str] | None = None
    attachments: list[str] | None = None
    html: bool = False
    reply_to_id: str | None = None
    forward_id: str | None = None


@dataclasses.dataclass(frozen=True)
class EventFields:
    """Fields for creating a calendar event."""

    subject: str
    start: str
    timezone: str
    end: str | None = None
    location: str | None = None
    body: str | None = None
    attendees: list[str] | None = None
    calendar_name: str | None = None
    is_all_day: bool = False
    recurrence: str | None = None
    recurrence_end_date: str | None = None


@dataclasses.dataclass(frozen=True)
class EventPatch:
    """Fields for updating a calendar event; None means leave unchanged."""

    subject: str | None = None
    start: str | None = None
    end: str | None = None
    location: str | None = None
    body: str | None = None
    timezone: str | None = None
    reminder_on: bool | None = None
    reminder_minutes: int | None = None
