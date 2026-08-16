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
    reply_all: bool = False
    forward_id: str | None = None


# Stamped onto every event this CLI creates, and surfaced by the list formatter.
#
# WHY: once it is on the calendar, an event the agent created from a tip, a guess or a draft plan
# is indistinguishable from one the user actually committed to. Reading it back days later and
# treating it as the user's intent turns the agent's own suggestion into evidence, and any date
# arithmetic built on it inherits the invention. A convention of writing "added by <agent>" into
# the body does not survive: the default list does not fetch bodies, and nobody re-reads a body
# they wrote themselves. `categories` is the field Outlook provides for exactly this, it is cheap
# to select, and it renders as a label in the user's own client, so provenance is visible to BOTH
# sides. It lives here because this module is a leaf; importing it from `calendar` would pull msal
# into the formatter.
AGENT_EVENT_CATEGORY = "vesta"


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
    categories: list[str] | None = None


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
