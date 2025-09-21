import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from . import graph, auth, notifications

_base_dir: Path | None = None
_state_file: Path | None = None
_log_file: Path | None = None
logger: logging.Logger | None = None


def init_monitor(base_dir: Path, state_file: Path, log_file: Path):
    global _base_dir, _state_file, _log_file, logger
    _base_dir = base_dir
    _state_file = state_file
    _log_file = log_file

    _base_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("microsoft_mcp.monitor")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        file_handler = logging.FileHandler(_log_file)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)


def run():
    assert _state_file and logger
    logger.info("Monitor thread started")
    first_run = True
    catching_up = False

    while True:
        try:
            # On first run, check if we were offline and need to catch up
            if first_run and _state_file.exists():
                last_check_str = _state_file.read_text().strip()
                last_check_dt = datetime.fromisoformat(
                    last_check_str.replace("Z", "+00:00")
                )
                gap_seconds = (
                    datetime.now(timezone.utc) - last_check_dt
                ).total_seconds()

                # If gap > 120s (normal is 60s), we were offline - use old timestamp to catch up
                if gap_seconds > 120:
                    logger.info(
                        f"Detected offline period of {gap_seconds:.0f}s, catching up from {last_check_str}"
                    )
                    last_check = last_check_str
                    catching_up = True
                else:
                    last_check = (
                        datetime.now(timezone.utc) - timedelta(hours=1)
                    ).isoformat()
                first_run = False
            else:
                last_check = (
                    _state_file.read_text().strip()
                    if _state_file.exists()
                    else (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                )
                catching_up = False

            logger.info(f"Checking for updates since {last_check}")

            new_check_time = datetime.now(timezone.utc)

            for acc in auth.list_accounts():
                logger.info(f"Checking account: {acc.username}")

                try:
                    result = graph.request(
                        "GET",
                        "/me/mailFolders/inbox/messages",
                        acc.account_id,
                        params={
                            "$filter": f"receivedDateTime gt {last_check}",
                            "$select": "subject,from,bodyPreview,receivedDateTime",
                            "$top": 50,
                        },
                    )

                    emails = (result or {}).get("value", [])
                    logger.info(f"Found {len(emails)} new emails for {acc.username}")

                    for email in emails:
                        sender = email.get("from", {}).get("emailAddress", {})
                        logger.info(
                            f"Writing notification for email from {sender.get('address')}"
                        )
                        metadata = {
                            "account": acc.username,
                            "subject": email.get("subject"),
                            "sender_name": sender.get("name"),
                            "sender_address": sender.get("address"),
                            "preview": email.get("bodyPreview", "")[:200],
                            "received_at": email.get("receivedDateTime"),
                        }
                        if catching_up:
                            metadata["missed"] = True
                        notifications.write_notification(
                            "email",
                            f"New email from {sender.get('name') or sender.get('address', 'Unknown')}: {email.get('subject', '(No subject)')}",
                            metadata,
                        )
                except Exception as e:
                    logger.error(f"Error fetching emails for {acc.username}: {e}")

                try:
                    now = datetime.now(timezone.utc)
                    # If catching up, also check for events that happened during offline period
                    if catching_up:
                        start_time = datetime.fromisoformat(
                            last_check.replace("Z", "+00:00")
                        )
                    else:
                        start_time = now

                    cal_result = graph.request(
                        "GET",
                        "/me/calendarView",
                        acc.account_id,
                        params={
                            "startDateTime": start_time.isoformat().replace(
                                "+00:00", "Z"
                            ),
                            "endDateTime": (now + timedelta(minutes=15))
                            .isoformat()
                            .replace("+00:00", "Z"),
                            "$select": "subject,start,location",
                        },
                    )

                    events = (cal_result or {}).get("value", [])
                    logger.info(
                        f"Found {len(events)} upcoming calendar events for {acc.username}"
                    )

                    for event in events:
                        start = event.get("start", {}).get("dateTime")
                        event_time = (
                            datetime.fromisoformat(start.replace("Z", "+00:00"))
                            if start
                            else now
                        )
                        mins = (
                            int((event_time - now).total_seconds() / 60) if start else 0
                        )

                        loc = event.get("location", {}).get("displayName")
                        logger.info(
                            f"Writing notification for calendar event: {event.get('subject')}"
                        )

                        # Determine event status
                        if mins < -5:
                            time_desc = f"occurred {-mins} minutes ago"
                        elif mins < 0:
                            time_desc = "just occurred"
                        elif mins == 0:
                            time_desc = "now"
                        else:
                            time_desc = f"in {mins} minutes"

                        metadata = {
                            "account": acc.username,
                            "subject": event.get("subject"),
                            "start_time": start,
                            "location": loc,
                            "minutes_until": mins if start else None,
                        }
                        if catching_up and mins < 0:
                            metadata["missed"] = True

                        notifications.write_notification(
                            "calendar",
                            f"Calendar event {time_desc}: {event.get('subject', '(No title)')}"
                            + (f" at {loc}" if loc else ""),
                            metadata,
                        )
                except Exception as e:
                    logger.error(f"Error fetching calendar for {acc.username}: {e}")

            _state_file.write_text(new_check_time.isoformat())
            logger.info("Completed check cycle, sleeping for 60 seconds")
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}", exc_info=True)
            time.sleep(60)
