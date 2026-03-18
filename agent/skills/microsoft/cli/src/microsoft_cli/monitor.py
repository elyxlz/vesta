from datetime import datetime, timedelta, UTC
from typing import TypedDict, NotRequired
from zoneinfo import ZoneInfo
from . import graph, auth, notifications
from .context import MicrosoftContext


class EmailAddress(TypedDict):
    name: NotRequired[str]
    address: str


class EmailFrom(TypedDict):
    emailAddress: EmailAddress


class Email(TypedDict):
    id: str
    subject: NotRequired[str]
    from_: NotRequired[EmailFrom]  # 'from' is reserved
    bodyPreview: NotRequired[str]
    receivedDateTime: NotRequired[str]


class EventTime(TypedDict):
    dateTime: str
    timeZone: NotRequired[str]


class EventLocation(TypedDict):
    displayName: NotRequired[str]


class CalendarEvent(TypedDict):
    id: str
    subject: NotRequired[str]
    start: EventTime
    location: NotRequired[EventLocation]


def _parse_event_time(event: CalendarEvent) -> datetime:
    """Parse event start time to UTC-aware datetime. Raises ValueError on failure."""
    start = event["start"]
    start_dt = start["dateTime"]
    start_tz = start["timeZone"] if "timeZone" in start else None

    # Check for timezone info: Z, +HH:MM, or -HH:MM
    has_tz = start_dt.endswith("Z") or "+" in start_dt or (start_dt.count("-") > 2)
    if has_tz:
        return datetime.fromisoformat(start_dt.replace("Z", "+00:00"))

    # Local time without timezone - use the event's timeZone field
    if not start_tz:
        raise ValueError(f"Event has dateTime without timezone info: {start_dt}")
    try:
        naive_time = datetime.fromisoformat(start_dt)
        local_tz = ZoneInfo(start_tz)
        return naive_time.replace(tzinfo=local_tz).astimezone(UTC)
    except Exception as e:
        raise ValueError(f"Failed to parse event time {start_dt} with tz {start_tz}: {e}")


def _format_threshold_label(minutes: int) -> str:
    """Convert minutes to human-readable label like '1 week', '2 hours'."""
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


def run(ctx: MicrosoftContext):
    logger = ctx.monitor_logger
    logger.info("Monitor thread started")
    first_run = True
    catching_up = False

    while not ctx.monitor_stop_event.is_set():
        try:
            last_check = (
                ctx.monitor_state_file.read_text().strip()
                if ctx.monitor_state_file.exists()
                else (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            )
            catching_up = False

            if first_run:
                last_check_dt = datetime.fromisoformat(last_check.replace("Z", "+00:00"))
                gap_seconds = (datetime.now(UTC) - last_check_dt).total_seconds()
                if gap_seconds > 90:
                    logger.info(f"Detected offline period of {gap_seconds:.0f}s, catching up from {last_check}")
                    catching_up = True
            first_run = False

            logger.info(f"Checking for updates since {last_check}")
            last_dt = datetime.fromisoformat(last_check.replace("Z", "+00:00"))

            new_check_time = datetime.now(UTC)

            for acc in auth.list_accounts(ctx.cache_file, settings=ctx.settings):
                logger.info(f"Checking account: {acc.username}")

                try:
                    result = graph.request(
                        ctx.http_client,
                        ctx.cache_file,
                        ctx.scopes,
                        ctx.settings,
                        ctx.base_url,
                        "GET",
                        "/me/mailFolders/inbox/messages",
                        acc.account_id,
                        params={
                            "$filter": f"receivedDateTime gt {last_check}",
                            "$select": "subject,from,bodyPreview,receivedDateTime",
                            "$top": 50,
                        },
                    )

                    if not result or "value" not in result:
                        logger.warning(f"Unexpected email API response: {result}")
                        continue
                    emails = result["value"]
                    logger.info(f"Found {len(emails)} new emails for {acc.username}")

                    for email in emails:
                        email_from = email["from"] if "from" in email else None
                        if not email_from or "emailAddress" not in email_from:
                            logger.warning(f"Email missing sender info: {email['id'] if 'id' in email else '?'}")
                            continue
                        sender = email_from["emailAddress"]
                        sender_name = sender["name"] if "name" in sender else None
                        sender_addr = sender["address"] if "address" in sender else None
                        if not sender_addr:
                            logger.warning(f"Email sender missing address: {email['id'] if 'id' in email else '?'}")
                            continue

                        logger.info(f"Writing notification for email from {sender_addr}")
                        notifications.write_notification(
                            ctx.notif_dir,
                            "email",
                            sender=sender_name or sender_addr,
                            subject=email["subject"] if "subject" in email else None,
                            preview=(email["bodyPreview"] if "bodyPreview" in email else "")[:200],
                            sender_address=sender_addr,
                            account=acc.username,
                            received_at=email["receivedDateTime"] if "receivedDateTime" in email else None,
                            missed=catching_up or None,
                        )
                except Exception as e:
                    logger.error(f"Error fetching emails for {acc.username}: {e}")

                try:
                    max_threshold = max(ctx.get_calendar_notify_thresholds())
                    window_end = new_check_time + timedelta(minutes=max_threshold + 60)
                    cal_result = graph.request(
                        ctx.http_client,
                        ctx.cache_file,
                        ctx.scopes,
                        ctx.settings,
                        ctx.base_url,
                        "GET",
                        "/me/calendarView",
                        acc.account_id,
                        params={
                            "startDateTime": last_dt.isoformat().replace("+00:00", "Z"),
                            "endDateTime": window_end.isoformat().replace("+00:00", "Z"),
                            "$select": "subject,start,location,id",
                        },
                    )

                    if not cal_result or "value" not in cal_result:
                        logger.warning(f"Unexpected calendar API response: {cal_result}")
                        continue
                    events = cal_result["value"]
                    logger.info(f"Found {len(events)} upcoming calendar events for {acc.username}")

                    for event in events:
                        try:
                            event_time = _parse_event_time(event)
                        except (KeyError, ValueError) as e:
                            logger.warning(f"Skipping event {event['id'] if 'id' in event else '?'}: {e}")
                            continue

                        start_dt = event["start"]["dateTime"]
                        location = event["location"] if "location" in event else None
                        loc = location["displayName"] if location and "displayName" in location else None
                        subject = (event["subject"] if "subject" in event else None) or "(No title)"
                        mins_until = int((event_time - new_check_time).total_seconds() / 60)

                        for threshold_mins in ctx.get_calendar_notify_thresholds():
                            trigger_time = event_time - timedelta(minutes=threshold_mins)
                            if not (last_dt <= trigger_time < new_check_time):
                                continue

                            label = _format_threshold_label(threshold_mins)
                            logger.info(f"Writing {label} reminder for calendar event: {subject}")

                            notifications.write_notification(
                                ctx.notif_dir,
                                "calendar",
                                subject=subject,
                                start_time=start_dt,
                                minutes_until=mins_until,
                                reminder_window=label,
                                location=loc,
                                account=acc.username,
                                missed=(catching_up and event_time < new_check_time) or None,
                            )
                except Exception as e:
                    logger.error(f"Error fetching calendar for {acc.username}: {e}")

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
