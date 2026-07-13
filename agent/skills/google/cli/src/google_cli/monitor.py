import re
from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from . import api, calendar, google_health, notifications
from .context import GoogleContext
from .gmail import _get_header


# Zero-width / bidi formatting characters that marketing emails use to pad previews.
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠⁦-⁩﻿]")
_WHITESPACE_RUN = re.compile(r"\s+")

# Cap how far back a first-run catch-up reaches. A long offline gap (e.g. the
# daemon restarting with a fresh token after the old one expired) otherwise
# replays weeks of unread email and past calendar events as notifications.
MAX_CATCHUP_LOOKBACK = timedelta(hours=24)


def clamp_catchup_start(last_check_dt: datetime, now: datetime) -> datetime:
    return max(last_check_dt, now - MAX_CATCHUP_LOOKBACK)


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
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))

    if tz_name:
        try:
            naive = datetime.fromisoformat(date_str)
            return naive.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)
        except (KeyError, ValueError):
            pass

    return datetime.fromisoformat(date_str).replace(tzinfo=UTC)


def run(ctx: GoogleContext):
    config = ctx.config
    logger = ctx.monitor_logger
    logger.info("Monitor thread started")
    first_run = True
    catching_up = False

    while not ctx.monitor_stop_event.is_set():
        try:
            if ctx.monitor_state_file.exists():
                last_check_str = ctx.monitor_state_file.read_text().strip()
            else:
                last_check_str = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

            last_check_dt = datetime.fromisoformat(last_check_str.replace("Z", "+00:00"))
            new_check_time = datetime.now(UTC)

            catching_up = False
            if first_run:
                gap_seconds = (new_check_time - last_check_dt).total_seconds()
                if gap_seconds > 90:
                    logger.info(f"Detected offline period of {gap_seconds:.0f}s, catching up from {last_check_str}")
                    catching_up = True
            first_run = False

            query_since = clamp_catchup_start(last_check_dt, new_check_time)
            if query_since != last_check_dt:
                logger.info(f"Clamping catch-up window from {last_check_str} to {query_since.isoformat()}")

            logger.info(f"Checking for updates since {query_since.isoformat()}")

            # Low-frequency (≤ once/day) OAuth client health probe + automatic
            # self-heal ladder. Silent when it can swap in a fresh Thunderbird
            # client; only ever reaches the user as a last resort. Isolated in its
            # own try so a probe error never disrupts mail/calendar polling.
            try:
                google_health.maybe_run_daily_probe(config, ctx.notif_dir, log=logger.info)
            except Exception as e:
                logger.error(f"Error in google-health probe: {e}")

            try:
                gmail = api.gmail_service(config)

                epoch_seconds = int(query_since.timestamp())
                query = f"after:{epoch_seconds}"
                results = gmail.users().messages().list(userId="me", q=query, labelIds=["INBOX"], maxResults=50).execute()
                messages = results["messages"] if "messages" in results else []
                logger.info(f"Found {len(messages)} new emails")

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
                        logger.error(f"Error processing email {msg_ref['id'] if 'id' in msg_ref else '?'}: {e}")

            except HttpError as e:
                logger.error(f"Error fetching Gmail: {e}")

            try:
                max_threshold = max(config.get_calendar_notify_thresholds())
                window_end = new_check_time + timedelta(minutes=max_threshold + 60)

                # Calendar runs on CalDAV now (the REST API is disabled for the
                # reused Thunderbird client). list_events_between returns the same
                # REST-shaped event dicts this loop already consumes.
                events = calendar.list_events_between(
                    config,
                    calendar_id="primary",
                    start=query_since,
                    end=window_end,
                    include_details=False,
                    limit=50,
                )
                logger.info(f"Found {len(events)} upcoming calendar events")

                for event in events:
                    try:
                        event_time = _parse_event_time(event)
                    except (KeyError, ValueError) as e:
                        logger.warning(f"Skipping event {event['id'] if 'id' in event else '?'}: {e}")
                        continue

                    subject = event["summary"] if "summary" in event else "(No title)"
                    location = event["location"] if "location" in event else None
                    mins_until = int((event_time - new_check_time).total_seconds() / 60)

                    for threshold_mins in config.get_calendar_notify_thresholds():
                        trigger_time = event_time - timedelta(minutes=threshold_mins)
                        if not (query_since <= trigger_time < new_check_time):
                            continue

                        label = _format_threshold_label(threshold_mins)
                        logger.info(f"Writing {label} reminder for: {subject}")

                        start_info = event["start"] if "start" in event else {}
                        start_str = (start_info["dateTime"] if "dateTime" in start_info else None) or (
                            start_info["date"] if "date" in start_info else ""
                        )

                        notifications.write_notification(
                            ctx.notif_dir,
                            "calendar",
                            subject=subject,
                            start_time=strip_fractional(start_str),
                            minutes_until=mins_until,
                            location=location,
                            missed=(catching_up and event_time < new_check_time) or None,
                        )

            except Exception as e:
                # CalDAV surfaces its own error type, not HttpError; a calendar
                # failure must not sink the whole poll cycle (Gmail still ran).
                logger.error(f"Error fetching calendar: {e}")

            tmp = ctx.monitor_state_file.with_suffix(".tmp")
            tmp.write_text(new_check_time.isoformat())
            tmp.rename(ctx.monitor_state_file)
            logger.info("Completed check cycle, sleeping for 45 seconds")
            if ctx.monitor_stop_event.wait(45):
                break

        except Exception as e:
            logger.error(f"Error in monitor loop: {e}", exc_info=True)
            if ctx.monitor_stop_event.wait(45):
                break

    logger.info("Monitor thread stopped")
