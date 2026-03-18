---
name: zoom
description: This skill should be used when the user asks about "zoom", "zoom meeting", "zoom call", or needs to create, list, or delete Zoom meetings.
---

# Zoom — CLI: zoom

**Setup**: See [SETUP.md](SETUP.md)

## Meeting

### Quick Reference
```bash
zoom meeting create --topic "Standup" --duration 30
zoom meeting list
zoom meeting delete --id <meeting_id>
```

### Other Commands
```bash
zoom meeting create --topic "Project Review" --duration 60 --start-time "2025-11-15T14:00:00" --timezone "Europe/London"
```

## Notes
- No daemon needed — Zoom CLI makes direct API calls
- `--duration` is in minutes
- `--start-time` is optional — omit for an instant meeting
- `--timezone` uses IANA names (e.g., "Europe/London", "America/New_York")
- To add a Zoom link to a Google Calendar event, create the meeting first, then pass the `join_url` as `--location` or `--body` to `google calendar create`

## Scheduling Preferences
[User's preferred meeting durations, buffer time between meetings]
