import time
from datetime import datetime, timedelta
from pathlib import Path
from . import graph, auth, notifications

STATE_FILE = Path("data/microsoft/last_check")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

def run():
    while True:
        last_check = STATE_FILE.read_text().strip() if STATE_FILE.exists() else (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"

        for acc in auth.list_accounts():
            for email in graph.request(acc.account_id, "GET", "/me/mailFolders/inbox/messages", params={
                "$filter": f"receivedDateTime gt {last_check}",
                "$select": "subject,from,bodyPreview,receivedDateTime",
                "$top": 50
            }).json().get("value", []):
                sender = email.get("from", {}).get("emailAddress", {})
                notifications.write_notification(
                    "email",
                    f"New email from {sender.get('name') or sender.get('address', 'Unknown')}: {email.get('subject', '(No subject)')}",
                    {
                        "account": acc.username,
                        "subject": email.get("subject"),
                        "sender_name": sender.get("name"),
                        "sender_address": sender.get("address"),
                        "preview": email.get("bodyPreview", "")[:200],
                        "received_at": email.get("receivedDateTime")
                    }
                )

            now = datetime.utcnow()
            for event in graph.request(acc.account_id, "GET", "/me/calendarView", params={
                "startDateTime": now.isoformat() + "Z",
                "endDateTime": (now + timedelta(minutes=15)).isoformat() + "Z",
                "$select": "subject,start,location"
            }).json().get("value", []):
                start = event.get("start", {}).get("dateTime")
                mins = int((datetime.fromisoformat(start.replace("Z", "+00:00")) - now).total_seconds() / 60) if start else 0
                loc = event.get("location", {}).get("displayName")
                notifications.write_notification(
                    "calendar",
                    f"Calendar event {'in ' + str(mins) + ' minutes' if mins > 0 else 'now'}: {event.get('subject', '(No title)')}" + (f" at {loc}" if loc else ""),
                    {
                        "account": acc.username,
                        "subject": event.get("subject"),
                        "start_time": start,
                        "location": loc,
                        "minutes_until": mins if start else None
                    }
                )

        STATE_FILE.write_text(datetime.utcnow().isoformat() + "Z")
        time.sleep(60)
