import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from . import graph, auth, notifications

BASE_DIR = Path(__file__).parent.parent.parent / "data"
BASE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = BASE_DIR / "last_check"
LOG_FILE = BASE_DIR / "monitor.log"

logger = logging.getLogger("microsoft_mcp.monitor")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(file_handler)


def run():
    logger.info("Monitor thread started")
    while True:
        try:
            last_check = (
                STATE_FILE.read_text().strip()
                if STATE_FILE.exists()
                else (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            )
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
                        notifications.write_notification(
                            "email",
                            f"New email from {sender.get('name') or sender.get('address', 'Unknown')}: {email.get('subject', '(No subject)')}",
                            {
                                "account": acc.username,
                                "subject": email.get("subject"),
                                "sender_name": sender.get("name"),
                                "sender_address": sender.get("address"),
                                "preview": email.get("bodyPreview", "")[:200],
                                "received_at": email.get("receivedDateTime"),
                            },
                        )
                except Exception as e:
                    logger.error(f"Error fetching emails for {acc.username}: {e}")

                try:
                    now = datetime.now(timezone.utc)
                    cal_result = graph.request(
                        "GET",
                        "/me/calendarView",
                        acc.account_id,
                        params={
                            "startDateTime": now.isoformat().replace("+00:00", "Z"),
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
                        mins = (
                            int(
                                (
                                    datetime.fromisoformat(start.replace("Z", "+00:00"))
                                    - now
                                ).total_seconds()
                                / 60
                            )
                            if start
                            else 0
                        )
                        loc = event.get("location", {}).get("displayName")
                        logger.info(
                            f"Writing notification for calendar event: {event.get('subject')}"
                        )
                        notifications.write_notification(
                            "calendar",
                            f"Calendar event {'in ' + str(mins) + ' minutes' if mins > 0 else 'now'}: {event.get('subject', '(No title)')}"
                            + (f" at {loc}" if loc else ""),
                            {
                                "account": acc.username,
                                "subject": event.get("subject"),
                                "start_time": start,
                                "location": loc,
                                "minutes_until": mins if start else None,
                            },
                        )
                except Exception as e:
                    logger.error(f"Error fetching calendar for {acc.username}: {e}")

            STATE_FILE.write_text(new_check_time.isoformat())
            logger.info("Completed check cycle, sleeping for 60 seconds")
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}", exc_info=True)
            time.sleep(60)
