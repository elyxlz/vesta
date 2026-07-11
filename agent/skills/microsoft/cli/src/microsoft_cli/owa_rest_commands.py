"""OWA REST command adapters.

These mirror the signatures of the Graph command functions in ``email.py`` and
``calendar.py`` and the EWS adapters in ``owa_commands.py``, but route through
the REST transport in ``owa_rest.py``.  The dispatcher in ``backend.py`` and the
CLI in ``cli.py`` call whichever path matches the ``--backend`` choice.

Token source: browser-captured token stored per-account by ``auth owa-login``.
"""

from __future__ import annotations

import base64
import datetime as dt
import pathlib as pl
from zoneinfo import ZoneInfo

from . import owa_rest
from . import email as email_mod
from .config import Config


def _to_utc_z(value: str, timezone: str) -> str:
    """Convert a wall-clock datetime string in ``timezone`` (IANA) to UTC ``...Z``."""
    raw = value.replace("Z", "")
    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------


def list_emails(config: Config, client, *, account_email: str, folder: str = "inbox", limit: int = 10) -> list[dict]:
    return owa_rest.list_messages(client, account_email, config, folder=folder, limit=limit)


def search_emails(config: Config, client, *, account_email: str, query: str, limit: int = 10, folder: str | None = None) -> list[dict]:
    return owa_rest.search_messages(client, account_email, config, query=query, folder=folder, limit=limit)


def get_email(
    config: Config, client, *, account_email: str, email_id: str, include_attachments: bool = True, save_to_file: str | None = None
) -> dict:
    msg = owa_rest.get_message(client, account_email, config, item_id=email_id)
    return email_mod.finalize_email_body(config, email_id, msg, save_to_file)


def send_email(
    config: Config,
    client,
    *,
    account_email: str,
    to: list[str] | None,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[str] | None = None,
    html: bool = False,
) -> dict:
    if not to and not cc and not bcc:
        raise ValueError("at least one recipient is required (--to, --cc, or --bcc)")
    return owa_rest.send_message(
        client, account_email, config, to=to, subject=subject, body=body, cc=cc, bcc=bcc, attachments=attachments, html=html
    )


def create_email_draft(
    config: Config,
    client,
    *,
    account_email: str,
    body: str,
    subject: str | None = None,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[str] | None = None,
    reply_to_id: str | None = None,
    forward_id: str | None = None,
) -> dict:
    if reply_to_id and forward_id:
        raise ValueError("specify at most one of --reply-to or --forward")
    if not (reply_to_id or forward_id):
        if not subject:
            raise ValueError("--subject is required for a new draft")
        if not to and not cc and not bcc:
            raise ValueError("at least one recipient is required (--to, --cc, or --bcc)")
    return owa_rest.create_draft(
        client,
        account_email,
        config,
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        attachments=attachments,
        reply_to_id=reply_to_id,
        forward_id=forward_id,
    )


def reply_to_email(
    config: Config,
    client,
    *,
    account_email: str,
    email_id: str,
    body: str,
    attachments: list[str] | None = None,
    reply_all: bool = False,
    html: bool = False,
) -> dict:
    return owa_rest.reply_message(
        client, account_email, config, item_id=email_id, body=body, attachments=attachments, reply_all=reply_all, html=html
    )


def forward_email(
    config: Config,
    client,
    *,
    account_email: str,
    email_id: str,
    to: list[str],
    body: str = "",
    cc: list[str] | None = None,
    attachments: list[str] | None = None,
    html: bool = False,
) -> dict:
    if not to:
        raise ValueError("--to is required to forward")
    return owa_rest.forward_message(
        client, account_email, config, item_id=email_id, to=to, body=body, cc=cc, attachments=attachments, html=html
    )


def move_email(config: Config, client, *, account_email: str, email_id: str, to_folder: str) -> dict:
    destination = owa_rest.resolve_folder_id(client, account_email, config, folder=to_folder)
    result = owa_rest.move_message(client, account_email, config, item_id=email_id, destination=destination)
    result["to_folder"] = to_folder
    return result


def archive_email(config: Config, client, *, account_email: str, email_id: str) -> dict:
    return move_email(config, client, account_email=account_email, email_id=email_id, to_folder="archive")


def get_attachment(config: Config, client, *, account_email: str, email_id: str, attachment_id: str, save_path: str) -> dict:
    att = owa_rest.get_attachment(client, account_email, config, email_id=email_id, attachment_id=attachment_id)
    path = pl.Path(save_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = att.get("contentBytes") or ""
    path.write_bytes(base64.b64decode(content_bytes))
    return {"name": att.get("name"), "content_type": att.get("contentType"), "saved_to": str(path)}


def list_attachments(config: Config, client, *, account_email: str, email_id: str) -> list[dict]:
    return owa_rest.list_attachments(client, account_email, config, email_id=email_id)


def download_attachments(config: Config, client, *, account_email: str, email_id: str, out_dir: str) -> dict:
    return owa_rest.download_attachments(client, account_email, config, email_id=email_id, out_dir=out_dir)


def update_email(
    config: Config,
    client,
    *,
    account_email: str,
    email_id: str,
    is_read: bool | None = None,
    categories: list[str] | None = None,
    flagged: bool | None = None,
) -> dict:
    if is_read is None and categories is None and flagged is None:
        raise ValueError("must specify at least one field to update (is_read, categories, or flagged)")
    return owa_rest.update_message(client, account_email, config, item_id=email_id, is_read=is_read, categories=categories, flagged=flagged)


def delete_email(
    config: Config, client, *, account_email: str, email_id: str | None = None, sender: str | None = None, permanent: bool = False
) -> dict:
    if (email_id is None) == (sender is None):
        raise ValueError("specify exactly one of --id or --sender")
    if email_id is not None:
        return owa_rest.delete_message(client, account_email, config, item_id=email_id, permanent=permanent)
    return owa_rest.delete_by_sender(client, account_email, config, sender=sender, permanent=permanent)


# Block/unblock: OWA REST v2.0 does not expose inbox message rules; raise clearly.
def list_block_rules(config: Config, client, *, account_email: str):
    raise NotImplementedError("inbox rules are not available on the OWA REST path; use --backend graph")


def block_sender(config: Config, client, *, account_email: str, sender: str):
    raise NotImplementedError("inbox rules are not available on the OWA REST path; use --backend graph")


def unblock_sender(config: Config, client, *, account_email: str, sender: str):
    raise NotImplementedError("inbox rules are not available on the OWA REST path; use --backend graph")


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------


def list_folders(config: Config, client, *, account_email: str) -> list[dict]:
    return owa_rest.list_folders(client, account_email, config)


def folder_status(config: Config, client, *, account_email: str, folder: str) -> dict:
    return owa_rest.folder_status(client, account_email, config, folder=folder)


def create_folder(config: Config, client, *, account_email: str, name: str, parent_id: str | None = None) -> dict:
    return owa_rest.create_folder(client, account_email, config, name=name, parent_id=parent_id)


def rename_folder(config: Config, client, *, account_email: str, folder_id: str, name: str) -> dict:
    return owa_rest.rename_folder(client, account_email, config, folder_id=folder_id, name=name)


def delete_folder(config: Config, client, *, account_email: str, folder_id: str) -> dict:
    return owa_rest.delete_folder(client, account_email, config, folder_id=folder_id)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def list_events(
    config: Config,
    client,
    *,
    account_email: str,
    calendar_name: str | None = None,
    days_ahead: int = 7,
    days_back: int = 0,
    include_details: bool = True,
    user_timezone: str | None = None,
) -> list[dict]:
    tz = user_timezone or "UTC"
    now = dt.datetime.now(ZoneInfo(tz)) if tz != "UTC" else dt.datetime.now(dt.UTC)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = (start_of_today - dt.timedelta(days=days_back)).astimezone(dt.UTC)
    end = (start_of_today + dt.timedelta(days=days_ahead + 1)).astimezone(dt.UTC)

    def z(d: dt.datetime) -> str:
        return d.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return owa_rest.list_events(client, account_email, config, start_utc=z(start), end_utc=z(end), limit=100)


def list_calendars(config: Config, client, *, account_email: str) -> list[dict]:
    return owa_rest.list_calendars(client, account_email, config)


def get_event(config: Config, client, *, account_email: str, event_id: str, user_timezone: str | None = None) -> dict:
    return owa_rest.get_event(client, account_email, config, event_id=event_id)


def create_event(
    config: Config,
    client,
    *,
    account_email: str,
    subject: str,
    start: str,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    timezone: str,
    calendar_name: str | None = None,
    is_all_day: bool = False,
    recurrence: str | None = None,
    recurrence_end_date: str | None = None,
) -> dict:
    if recurrence:
        raise NotImplementedError("recurring events are not yet supported on the OWA REST path; use the Graph path")
    if is_all_day:
        start_date = start.split("T")[0]
        end_date = end.split("T")[0] if end else start_date
        su = f"{start_date}T00:00:00Z"
        eu = (
            f"{end_date}T00:00:00Z"
            if end_date != start_date
            else (dt.date.fromisoformat(start_date) + dt.timedelta(days=1)).isoformat() + "T00:00:00Z"
        )
        tz_out = "UTC"
    else:
        if not end:
            raise ValueError("end is required for non-all-day events")
        su = _to_utc_z(start, timezone)
        eu = _to_utc_z(end, timezone)
        tz_out = "UTC"
    return owa_rest.create_event(
        client,
        account_email,
        config,
        subject=subject,
        start=su,
        end=eu,
        timezone=tz_out,
        location=location,
        body=body,
        attendees=attendees,
        is_all_day=is_all_day,
    )


def update_event(
    config: Config,
    client,
    *,
    account_email: str,
    event_id: str,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    timezone: str | None = None,
) -> dict:
    su = _to_utc_z(start, timezone) if start is not None else None
    eu = _to_utc_z(end, timezone) if end is not None else None
    return owa_rest.update_event(
        client,
        account_email,
        config,
        event_id=event_id,
        subject=subject,
        start=su,
        end=eu,
        location=location,
        body=body,
        timezone="UTC",
    )


def delete_event(config: Config, client, *, account_email: str, event_id: str, send_cancellation: bool = True) -> dict:
    return owa_rest.delete_event(client, account_email, config, event_id=event_id, send_cancellation=send_cancellation)


def respond_event(config: Config, client, *, account_email: str, event_id: str, response: str = "accept", message: str | None = None) -> dict:
    return owa_rest.respond_event(client, account_email, config, event_id=event_id, response=response, message=message)
