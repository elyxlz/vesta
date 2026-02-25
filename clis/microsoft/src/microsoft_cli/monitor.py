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
    start_tz = start.get("timeZone")

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
            # On first run, check if we were offline and need to catch up
            if first_run and ctx.monitor_state_file.exists():
                last_check_str = ctx.monitor_state_file.read_text().strip()
                last_check_dt = datetime.fromisoformat(last_check_str.replace("Z", "+00:00"))
                gap_seconds = (datetime.now(UTC) - last_check_dt).total_seconds()

                # If gap > 120s (normal is 60s), we were offline - use old timestamp to catch up
                if gap_seconds > 120:
                    logger.info(f"Detected offline period of {gap_seconds:.0f}s, catching up from {last_check_str}")
                    last_check = last_check_str
                    catching_up = True
                else:
                    last_check = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            else:
                last_check = (
                    ctx.monitor_state_file.read_text().strip()
                    if ctx.monitor_state_file.exists()
                    else (datetime.now(UTC) - timedelta(hours=1)).isoformat()
                )
                catching_up = False
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
                        email_from = email.get("from")
                        if not email_from or "emailAddress" not in email_from:
                            logger.warning(f"Email missing sender info: {email.get('id')}")
                            continue
                        sender = email_from["emailAddress"]
                        sender_name = sender.get("name")
                        sender_addr = sender.get("address")
                        if not sender_addr:
                            logger.warning(f"Email sender missing address: {email.get('id')}")
                            continue

                        logger.info(f"Writing notification for email from {sender_addr}")
                        notifications.write_notification(
                            ctx.notif_dir,
                            "email",
                            sender=sender_name or sender_addr,
                            sender_address=sender_addr,
                            account=acc.username,
                            subject=email.get("subject"),
                            preview=(email.get("bodyPreview") or "")[:200],
                            received_at=email.get("receivedDateTime"),
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
                            logger.warning(f"Skipping event {event.get('id', '?')}: {e}")
                            continue

                        start_dt = event["start"]["dateTime"]
                        location = event.get("location")
                        loc = location.get("displayName") if location else None
                        subject = event.get("subject") or "(No title)"
                        mins_until = int((event_time - new_check_time).total_seconds() / 60)

                        for threshold_mins in ctx.get_calendar_notify_thresholds():
                            trigger_time = event_time - timedelta(minutes=threshold_mins)
                            if not (last_dt <= trigger_time < new_check_time):
                                continue

                            label = _format_threshold_label(threshold_mins)
                            logger.info(f"Writing {label} reminder for calendar event: {subject}")

                            if mins_until < -5:
                                pass
                            elif mins_until < 0:
                                pass
                            elif mins_until == 0:
                                pass
                            elif threshold_mins <= 60:
                                pass
                            else:
                                pass

                            notifications.write_notification(
                                ctx.notif_dir,
                                "calendar",
                                account=acc.username,
                                subject=subject,
                                start_time=start_dt,
                                location=loc,
                                minutes_until=mins_until,
                                reminder_window=label,
                                missed=(catching_up and event_time < new_check_time) or None,
                            )
                except Exception as e:
                    logger.error(f"Error fetching calendar for {acc.username}: {e}")

            ctx.monitor_state_file.write_text(new_check_time.isoformat())
            logger.info("Completed check cycle, sleeping for 60 seconds")
            if ctx.monitor_stop_event.wait(60):
                break
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}", exc_info=True)
            if ctx.monitor_stop_event.wait(60):
                break

    logger.info("Monitor thread stopped")
