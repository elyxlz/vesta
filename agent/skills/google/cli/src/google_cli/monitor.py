import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TypedDict
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from . import api, calendar, notifications
from .context import GoogleContext
from .gmail import _get_header

# Zero-width / bidi formatting characters that marketing emails use to pad previews.
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]")
_WHITESPACE_RUN = re.compile(r"\s+")

# Cap how far back a catch-up reaches. A long offline gap (e.g. the daemon
# restarting with a fresh token after the old one expired, or a token that was
# dead for a day) otherwise replays weeks of unread email and past calendar
# events as notifications.
MAX_CATCHUP_LOOKBACK = timedelta(hours=24)

# A gap wider than this means the unit missed a window (process down or token
# dead), so its recovered items are tagged `missed`.
_CATCHUP_GAP_SECONDS = 90

# A unit polled for the first time (fresh install or legacy state) resumes from here.
_FRESH_START_LOOKBACK = timedelta(hours=1)

# One-shot markers for terminal failures the user must act on: notify the agent
# once, then stay quiet until the failure clears (success removes the marker,
# re-arming the notification for a future failure).
AUTH_BROKEN_MARKER = "auth_broken.notified"
CALENDAR_BROKEN_MARKER = "calendar_broken.notified"


def clamp_catchup_start(last_check_dt: datetime, now: datetime) -> datetime:
    return max(last_check_dt, now - MAX_CATCHUP_LOOKBACK)


class MonitorState(TypedDict):
    """last_cycle seeds a unit polled for the first time; units maps "mail"/"calendar" to the end of
    the last window that unit read successfully, so a failed poll parks its own watermark alone."""

    last_cycle: str
    units: dict[str, str]


def _read_state(path: Path, now: datetime) -> MonitorState:
    """A legacy bare-timestamp file reads as a last_cycle with no units, so mail and calendar each
    resume from where the old single-watermark monitor left off."""
    raw = path.read_text().strip() if path.exists() else ""
    if not raw:
        return MonitorState(last_cycle=(now - _FRESH_START_LOOKBACK).isoformat(), units={})
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return MonitorState(last_cycle=raw, units={})
    match parsed:
        case {"last_cycle": str(last_cycle), "units": dict(units)}:
            return MonitorState(last_cycle=last_cycle, units={str(unit): str(watermark) for unit, watermark in units.items()})
        case _:
            raise ValueError(f"Malformed monitor state in {path}: {raw[:100]}")


def _write_state(path: Path, state: MonitorState) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.rename(path)


def _poll_unit(ctx: GoogleContext, state: MonitorState, unit: str, new_check_time: datetime, poll: Callable[[datetime, bool], bool]) -> None:
    """Advance the unit's watermark only when the poll read its window, so a failed poll (an outage)
    parks the watermark and the next healthy cycle re-reads the window instead of skipping it."""
    units = state["units"]
    seed = units[unit] if unit in units else state["last_cycle"]
    query_since = clamp_catchup_start(datetime.fromisoformat(seed), new_check_time)
    gap_seconds = (new_check_time - query_since).total_seconds()
    catching_up = gap_seconds > _CATCHUP_GAP_SECONDS
    if catching_up:
        ctx.monitor_logger.info("Catching up %s from %s, %.0fs behind", unit, query_since.isoformat(), gap_seconds)
    read = poll(query_since, catching_up)
    units[unit] = new_check_time.isoformat() if read else query_since.isoformat()


def notify_broken_once(ctx: GoogleContext, marker_name: str, notif_type: str, error: Exception) -> None:
    marker = ctx.monitor_base_dir / marker_name
    if marker.exists():
        return
    notifications.write_notification(ctx.notif_dir, notif_type, interrupt=True, error=str(error))
    marker.write_text(datetime.now(UTC).isoformat())


def clear_broken_marker(ctx: GoogleContext, marker_name: str) -> None:
    (ctx.monitor_base_dir / marker_name).unlink(missing_ok=True)


def clean_preview(text: str) -> str:
    return _WHITESPACE_RUN.sub(" ", _INVISIBLE.sub("", text)).strip()


def strip_fractional(iso: str) -> str:
    return re.sub(r"\.\d+", "", iso)


def _format_threshold_label(minutes: int) -> str:
    if minutes >= 10080:
        n = minutes // 10080
        return f"{n} week" + ("s" if n > 1 else "")
    if minutes >= 1440:
        n = minutes // 1440
        return f"{n} day" + ("s" if n > 1 else "")
    if minutes >= 60:
        n = minutes // 60
        return f"{n} hour" + ("s" if n > 1 else "")
    return f"{minutes} minute" + ("s" if minutes != 1 else "")


def _parse_event_time(event: dict) -> datetime:
    start = event["start"] if "start" in event else {}
    date_str = start["dateTime"] if "dateTime" in start else None
    if not date_str:
        date_only = start["date"] if "date" in start else None
        if date_only:
            return datetime.fromisoformat(date_only).replace(tzinfo=UTC)
        raise ValueError(f"Event has no start time: {event['id'] if 'id' in event else '?'}")

    tz_name = start["timeZone"] if "timeZone" in start else None
    has_tz = date_str.endswith("Z") or "+" in date_str or (date_str.count("-") > 2)

    if has_tz:
        return datetime.fromisoformat(date_str)

    if tz_name:
        try:
            naive = datetime.fromisoformat(date_str)
            return naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)
        except (KeyError, ValueError):
            pass

    return datetime.fromisoformat(date_str).replace(tzinfo=UTC)


def _poll_gmail(ctx: GoogleContext, gmail, query_since: datetime, catching_up: bool) -> bool:
    """Notify on Gmail arriving since query_since, returning True when the window was read. A failed
    list parks the watermark; a single message that cannot be fetched stays best-effort (the window was
    read, so re-reading would re-notify everything else)."""
    logger = ctx.monitor_logger
    try:
        epoch_seconds = int(query_since.timestamp())
        query = f"after:{epoch_seconds}"
        results = gmail.users().messages().list(userId="me", q=query, labelIds=["INBOX"], maxResults=50).execute()
        messages = results["messages"] if "messages" in results else []
        logger.info("Found %d new emails", len(messages))
    except HttpError as e:
        logger.error("Error fetching Gmail: %s", e)
        return False

    for msg_ref in messages:
        try:
            msg = (
                gmail.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"])
                .execute()
            )
            msg_payload = msg["payload"] if "payload" in msg else {}
            headers = msg_payload["headers"] if "headers" in msg_payload else []
            sender = _get_header(headers, "From")
            subject = _get_header(headers, "Subject")
            snippet = msg["snippet"] if "snippet" in msg else ""

            notifications.write_notification(
                ctx.notif_dir,
                "email",
                # Email pools by default (calendar reminders keep interrupting); the user adds
                # interrupt rules for the senders/keywords that should reach them right away.
                interrupt=False,
                sender=sender,
                subject=subject,
                preview=clean_preview(snippet)[:200],
                missed=catching_up or None,
            )
        except HttpError as e:
            logger.error("Error processing email %s: %s", msg_ref["id"] if "id" in msg_ref else "?", e)
    return True


def _notify_event_reminders(ctx: GoogleContext, event: dict, query_since: datetime, new_check_time: datetime, catching_up: bool) -> None:
    logger = ctx.monitor_logger
    try:
        event_time = _parse_event_time(event)
    except (KeyError, ValueError) as e:
        logger.warning("Skipping event %s: %s", event["id"] if "id" in event else "?", e)
        return

    subject = event["summary"] if "summary" in event else "(No title)"
    location = event["location"] if "location" in event else None
    mins_until = int((event_time - new_check_time).total_seconds() / 60)

    for threshold_mins in ctx.config.get_calendar_notify_thresholds():
        trigger_time = event_time - timedelta(minutes=threshold_mins)
        if not (query_since <= trigger_time < new_check_time):
            continue

        label = _format_threshold_label(threshold_mins)
        logger.info("Writing %s reminder for: %s", label, subject)

        start_info = event["start"] if "start" in event else {}
        start_str = (start_info["dateTime"] if "dateTime" in start_info else None) or (start_info["date"] if "date" in start_info else "")

        notifications.write_notification(
            ctx.notif_dir,
            "calendar",
            subject=subject,
            start_time=strip_fractional(start_str),
            minutes_until=mins_until,
            location=location,
            missed=(catching_up and event_time < new_check_time) or None,
        )


def _poll_calendar(ctx: GoogleContext, new_check_time: datetime, query_since: datetime, catching_up: bool) -> bool:
    """Emit calendar reminders crossing a threshold this cycle, returning True when the calendar was
    read. A failure parks the calendar watermark alone: mail carries its own, so a terminally broken
    calendar never re-notifies mail."""
    config = ctx.config
    logger = ctx.monitor_logger
    try:
        max_threshold = max(config.get_calendar_notify_thresholds())
        window_end = new_check_time + timedelta(minutes=max_threshold + 60)

        events = calendar.list_events_between(
            config,
            calendar_id="primary",
            start=query_since,
            end=window_end,
            include_details=False,
            limit=50,
        )
        logger.info("Found %d upcoming calendar events", len(events))

        for event in events:
            _notify_event_reminders(ctx, event, query_since, new_check_time, catching_up)

    except calendar.CalendarAuthError as e:
        # Calendar is terminally refused (e.g. a token minted under the old
        # shared client, whose project has the Calendar API disabled) while
        # Gmail still works: tell the agent once, keep polling mail.
        logger.error("Error fetching calendar: %s", e)
        notify_broken_once(ctx, CALENDAR_BROKEN_MARKER, "calendar_auth_broken", e)
        return False
    except Exception as e:
        # A calendar failure must not sink the whole poll cycle (Gmail still ran).
        logger.error("Error fetching calendar: %s", e)
        return False
    clear_broken_marker(ctx, CALENDAR_BROKEN_MARKER)
    return True


def run(ctx: GoogleContext):
    config = ctx.config
    logger = ctx.monitor_logger
    logger.info("Monitor thread started")

    while not ctx.monitor_stop_event.is_set():
        try:
            new_check_time = datetime.now(UTC)
            state = _read_state(ctx.monitor_state_file, new_check_time)

            try:
                gmail = api.gmail_service(config)
            except ValueError as e:
                # Terminal auth failure (no token, dead refresh): every poll would
                # fail, so tell the agent once and leave every watermark parked; the
                # next healthy cycle re-reads the gap (clamped to MAX_CATCHUP_LOOKBACK).
                logger.error("Google auth is broken: %s", e)
                notify_broken_once(ctx, AUTH_BROKEN_MARKER, "auth_broken", e)
                if ctx.monitor_stop_event.wait(45):
                    break
                continue
            clear_broken_marker(ctx, AUTH_BROKEN_MARKER)

            _poll_unit(ctx, state, "mail", new_check_time, partial(_poll_gmail, ctx, gmail))
            _poll_unit(ctx, state, "calendar", new_check_time, partial(_poll_calendar, ctx, new_check_time))

            state["last_cycle"] = new_check_time.isoformat()
            _write_state(ctx.monitor_state_file, state)
            logger.info("Completed check cycle, sleeping for 45 seconds")
            if ctx.monitor_stop_event.wait(45):
                break

        except Exception:
            logger.exception("Error in monitor loop")
            if ctx.monitor_stop_event.wait(45):
                break

    logger.info("Monitor thread stopped")
