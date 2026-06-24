"""OWA/EWS command adapters.

These mirror the signatures of the Graph command functions in ``email.py`` and
``calendar.py`` but route through the reverse-engineered EWS backend in
``owa.py``. They exist so the dispatcher in ``backend.py`` can call either path
with identical arguments and get identically shaped results.
"""

from __future__ import annotations

import base64
import datetime as dt
import pathlib as pl
from zoneinfo import ZoneInfo


from . import owa, auth, email as email_mod
from .config import Config
from .settings import MicrosoftSettings


def _settings() -> MicrosoftSettings:
    return MicrosoftSettings()


def _aid(config: Config, account_email: str, settings: MicrosoftSettings) -> str:
    return auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)


def _to_utc_z(value: str, timezone: str) -> str:
    """Convert a wall-clock datetime string in `timezone` (IANA) to UTC '...Z'.
    EWS interprets Start/End without an explicit zone as UTC, so we hand it UTC
    and sidestep the Windows-vs-IANA timezone-name mismatch entirely."""
    raw = value.replace("Z", "")
    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------
def list_emails(config, client, *, account_email, folder="inbox", limit=10):
    s = _settings()
    return owa.list_messages(client, config.cache_file, s, account_id=_aid(config, account_email, s), folder=folder, limit=limit)


def search_emails(config, client, *, account_email, query, limit=10, folder=None):
    s = _settings()
    return owa.search_messages(client, config.cache_file, s, account_id=_aid(config, account_email, s), query=query, folder=folder, limit=limit)


def get_email(config, client, *, account_email, email_id, include_attachments=True, save_to_file=None):
    s = _settings()
    msg = owa.get_message(client, config.cache_file, s, account_id=_aid(config, account_email, s), item_id=email_id)
    # Reuse the Graph path's body-to-disk persistence for an identical result shape.
    return email_mod.finalize_email_body(config, email_id, msg, save_to_file)


def send_email(config, client, *, account_email, to, subject, body, cc=None, bcc=None, attachments=None, html=False):
    if attachments:
        raise NotImplementedError("attachments are not yet supported on the OWA/EWS fallback path; use the Graph path for attachments")
    if not to and not cc and not bcc:
        raise ValueError("At least one recipient is required (--to, --cc, or --bcc)")
    s = _settings()
    return owa.send_message(
        client, config.cache_file, s, account_id=_aid(config, account_email, s), to=to, subject=subject, body=body, cc=cc, bcc=bcc, html=html
    )


def create_email_draft(config, client, *, account_email, to, subject, body, cc=None, bcc=None, attachments=None):
    if attachments:
        raise NotImplementedError("attachments are not yet supported on the OWA/EWS fallback path; use the Graph path for attachments")
    if not to and not cc and not bcc:
        raise ValueError("At least one recipient is required (--to, --cc, or --bcc)")
    s = _settings()
    return owa.create_draft(
        client, config.cache_file, s, account_id=_aid(config, account_email, s), to=to, subject=subject, body=body, cc=cc, bcc=bcc
    )


def reply_to_email(config, client, *, account_email, email_id, body, attachments=None, reply_all=False, html=False):
    if attachments:
        raise NotImplementedError("attachments are not yet supported on the OWA/EWS fallback path; use the Graph path for attachments")
    s = _settings()
    return owa.reply_message(
        client, config.cache_file, s, account_id=_aid(config, account_email, s), item_id=email_id, body=body, reply_all=reply_all, html=html
    )


def get_attachment(config, client, *, account_email, email_id, attachment_id, save_path):
    s = _settings()
    att = owa.get_attachment(client, config.cache_file, s, account_id=_aid(config, account_email, s), attachment_id=attachment_id)
    path = pl.Path(save_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(att["contentBytes"]))
    return {"name": att.get("name"), "content_type": att.get("contentType"), "saved_to": str(path)}


def update_email(config, client, *, account_email, email_id, is_read=None, categories=None):
    if is_read is None and categories is None:
        raise ValueError("Must specify at least one field to update (is_read or categories)")
    s = _settings()
    return owa.update_message(
        client, config.cache_file, s, account_id=_aid(config, account_email, s), item_id=email_id, is_read=is_read, categories=categories
    )


def delete_email(config, client, *, account_email, email_id=None, sender=None, permanent=False):
    if (email_id is None) == (sender is None):
        raise ValueError("Specify exactly one of --id or --sender")
    s = _settings()
    aid = _aid(config, account_email, s)
    if email_id is not None:
        return owa.delete_message(client, config.cache_file, s, account_id=aid, item_id=email_id, permanent=permanent)
    return owa.delete_by_sender(client, config.cache_file, s, account_id=aid, sender=sender, permanent=permanent)


def list_block_rules(config, client, *, account_email):
    s = _settings()
    return owa.list_block_rules(client, config.cache_file, s, account_id=_aid(config, account_email, s))


def block_sender(config, client, *, account_email, sender):
    s = _settings()
    return owa.block_sender(client, config.cache_file, s, account_id=_aid(config, account_email, s), sender=sender)


def unblock_sender(config, client, *, account_email, sender):
    s = _settings()
    return owa.unblock_sender(client, config.cache_file, s, account_id=_aid(config, account_email, s), sender=sender)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
def list_events(config, client, *, account_email, calendar_name=None, days_ahead=7, days_back=0, include_details=True, user_timezone=None):
    s = _settings()
    tz = user_timezone or "UTC"
    now = dt.datetime.now(ZoneInfo(tz)) if tz != "UTC" else dt.datetime.now(dt.UTC)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = (start_of_today - dt.timedelta(days=days_back)).astimezone(dt.UTC)
    end = (start_of_today + dt.timedelta(days=days_ahead + 1)).astimezone(dt.UTC)
    z = lambda d: d.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return owa.list_events(
        client, config.cache_file, s, account_id=_aid(config, account_email, s), start_utc=z(start), end_utc=z(end), limit=100
    )


def list_calendars(config, client, *, account_email):
    s = _settings()
    return owa.list_calendars(client, config.cache_file, s, account_id=_aid(config, account_email, s))


def get_event(config, client, *, account_email, event_id, user_timezone=None):
    s = _settings()
    return owa.get_event(client, config.cache_file, s, account_id=_aid(config, account_email, s), event_id=event_id)


def create_event(
    config,
    client,
    *,
    account_email,
    subject,
    start,
    end=None,
    location=None,
    body=None,
    attendees=None,
    timezone,
    calendar_name=None,
    is_all_day=False,
    recurrence=None,
    recurrence_end_date=None,
):
    if recurrence:
        raise NotImplementedError("recurring events are not yet supported on the OWA/EWS fallback path; use the Graph path")
    s = _settings()
    if is_all_day:
        # All-day: pass date-only as midnight UTC start, +1 day end.
        start_date = start.split("T")[0]
        end_date = end.split("T")[0] if end else start_date
        su = f"{start_date}T00:00:00Z"
        eu = (
            f"{end_date}T00:00:00Z"
            if end_date != start_date
            else (dt.date.fromisoformat(start_date) + dt.timedelta(days=1)).isoformat() + "T00:00:00Z"
        )
    else:
        if not end:
            raise ValueError("end is required for non-all-day events")
        su = _to_utc_z(start, timezone)
        eu = _to_utc_z(end, timezone)
    return owa.create_event(
        client,
        config.cache_file,
        s,
        account_id=_aid(config, account_email, s),
        subject=subject,
        start=su,
        end=eu,
        timezone="UTC",
        location=location,
        body=body,
        attendees=attendees,
        is_all_day=is_all_day,
    )


def update_event(config, client, *, account_email, event_id, subject=None, start=None, end=None, location=None, body=None, timezone=None):
    s = _settings()
    su = _to_utc_z(start, timezone) if start is not None else None
    eu = _to_utc_z(end, timezone) if end is not None else None
    return owa.update_event(
        client,
        config.cache_file,
        s,
        account_id=_aid(config, account_email, s),
        event_id=event_id,
        subject=subject,
        start=su,
        end=eu,
        location=location,
        body=body,
        timezone="UTC",
    )


def delete_event(config, client, *, account_email, event_id, send_cancellation=True):
    s = _settings()
    return owa.delete_event(
        client, config.cache_file, s, account_id=_aid(config, account_email, s), event_id=event_id, send_cancellation=send_cancellation
    )


def respond_event(config, client, *, account_email, event_id, response="accept", message=None):
    s = _settings()
    return owa.respond_event(
        client, config.cache_file, s, account_id=_aid(config, account_email, s), event_id=event_id, response=response, message=message
    )
