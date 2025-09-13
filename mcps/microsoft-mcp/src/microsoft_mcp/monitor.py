"""Poll Microsoft Graph for new emails and calendar events"""

import time
from datetime import datetime, timedelta
from pathlib import Path
from . import graph, auth, notifications

DATA_DIR = Path("data") / "microsoft"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "last_check"


def run():
    while True:
        last_check = (
            STATE_FILE.read_text().strip()
            if STATE_FILE.exists()
            else (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
        )

        for account in auth.list_accounts():
            # Check new emails
            emails = (
                graph.request(
                    account.account_id,
                    "GET",
                    "/me/mailFolders/inbox/messages",
                    params={
                        "$filter": f"receivedDateTime gt {last_check}",
                        "$select": "id,subject,from,bodyPreview,receivedDateTime",
                        "$top": 50,
                    },
                )
                .json()
                .get("value", [])
            )

            for email in emails:
                notifications.write_notification(
                    "email",
                    {
                        "subject": email.get("subject"),
                        "from": email.get("from", {})
                        .get("emailAddress", {})
                        .get("address"),
                        "preview": email.get("bodyPreview"),
                    },
                )

            # Check calendar (next 15 minutes)
            now = datetime.utcnow()
            events = (
                graph.request(
                    account.account_id,
                    "GET",
                    "/me/calendarView",
                    params={
                        "startDateTime": now.isoformat() + "Z",
                        "endDateTime": (now + timedelta(minutes=15)).isoformat() + "Z",
                        "$select": "subject,start,location",
                    },
                )
                .json()
                .get("value", [])
            )

            for event in events:
                notifications.write_notification(
                    "calendar",
                    {
                        "subject": event.get("subject"),
                        "start": event.get("start", {}).get("dateTime"),
                        "location": event.get("location", {}).get("displayName"),
                    },
                )

        STATE_FILE.write_text(datetime.utcnow().isoformat() + "Z")
        time.sleep(60)
