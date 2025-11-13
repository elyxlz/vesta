#!/usr/bin/env python3
"""Manual test of Microsoft Graph Calendar API with actual auth"""

import sys
import json
import datetime as dt
from pathlib import Path

# Add the microsoft-mcp source to path
sys.path.insert(0, str(Path(__file__).parent / "mcps" / "microsoft-mcp" / "src"))

from microsoft_mcp.settings import MicrosoftSettings
from microsoft_mcp import auth
import httpx


def test_calendar_api():
    """Test the calendar API manually"""

    # Load settings
    settings = MicrosoftSettings()

    # Auth file
    cache_file = Path("/home/elyx/vesta/data/microsoft-mcp/auth_cache.bin")

    # Get accounts
    print("=== Available Accounts ===")
    accounts = auth.list_accounts(cache_file, settings=settings)
    for i, acc in enumerate(accounts, 1):
        print(f"{i}. {acc.username} (ID: {acc.account_id})")

    if not accounts:
        print("ERROR: No accounts found!")
        return

    # Test ALL accounts
    for account in accounts:
        print(f"\n{'=' * 60}")
        print(f"=== Testing with account: {account.username} ===")
        print(f"{'=' * 60}")

        # Get token
        scopes = ["https://graph.microsoft.com/.default"]
        token = auth.get_token(cache_file, scopes, settings, account_id=account.account_id)
        print(f"✓ Got access token (length: {len(token)})")
        test_single_account(token)


def test_single_account(token: str):
    """Test calendar for a single account"""

    # Prepare calendar request
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    start = (now - dt.timedelta(days=0)).isoformat()  # Today
    end = (now + dt.timedelta(days=7)).isoformat()  # Next 7 days

    print("\n=== Calendar Query ===")
    print(f"Start: {start}")
    print(f"End:   {end}")

    # Make request
    url = "https://graph.microsoft.com/v1.0/me/calendarView"
    params = {
        "startDateTime": start,
        "endDateTime": end,
        "$orderby": "start/dateTime",
        "$top": 100,
        "$select": "id,subject,start,end,location,organizer",
    }

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    print(f"\nURL: {url}")
    print(f"Params: {json.dumps(params, indent=2)}")

    # Execute request
    print("\n=== Making API Call ===")
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers, params=params)

        print(f"Status Code: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")

        if response.status_code == 200:
            data = response.json()
            events = data.get("value", [])

            print("\n=== Results ===")
            print(f"Events found: {len(events)}")

            if events:
                print("\nEvents:")
                for i, event in enumerate(events, 1):
                    subject = event.get("subject", "No subject")
                    start_time = event.get("start", {}).get("dateTime", "Unknown")
                    print(f"  {i}. {subject} - {start_time}")
            else:
                print("\n⚠️  NO EVENTS RETURNED")
                print(f"Full response: {json.dumps(data, indent=2)}")
        else:
            print("\n❌ API Error!")
            print(f"Response body: {response.text}")


if __name__ == "__main__":
    test_calendar_api()
