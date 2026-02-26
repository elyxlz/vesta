"""Google Calendar skill template."""

SKILL_MD = """\
---
name: google-calendar
description: This skill should be used when the user asks about "Google Calendar", "gcal", or needs to manage events on a Google calendar.
---

# Google Calendar

## Status: Not yet set up

This skill needs a Google Calendar integration to be built. Vesta can build one using the Google Calendar API.

### Setup Notes
- Requires a Google Cloud project with the Calendar API enabled
- OAuth2 credentials (client_id, client_secret) for user authorization
- Scopes: `calendar.readonly`, `calendar.events` as needed
- Token storage for persistent access
- Can share OAuth credentials with the Gmail skill if both are set up

### Scheduling Preferences
[User's preferred meeting times, durations, buffer time]

### Regular Events
[Recurring meetings and commitments]
"""

SCRIPTS: dict[str, str] = {}
