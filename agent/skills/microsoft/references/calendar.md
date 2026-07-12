# Calendar (CLI: microsoft calendar)

Every command takes `--account <email>` and `--backend {auto,graph,owa-rest}` (see [SETUP.md](../SETUP.md)).

```bash
microsoft calendar list --account user@example.com --days-ahead 7
microsoft calendar calendars --account user@example.com                # list calendars
microsoft calendar get --account user@example.com --id <event_id>
microsoft calendar create --account user@example.com --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"
microsoft calendar update --account user@example.com --id <event_id> --start "2025-11-15T11:00:00" --timezone "Europe/London"
microsoft calendar respond --account user@example.com --id <event_id> --response accept
microsoft calendar delete --account user@example.com --id <event_id>
```

## Notes

- `--timezone` is required for `create`/`update` (IANA names like "Europe/London").
- `--response` choices: accept / decline / tentativelyAccept.
- `--to`/`--cc`/`--attendees` accept multiple space-separated values.
- `--no-cancellation` on `delete` skips notifying attendees.
- `--no-details` on `list` returns compact output (no body/attendees); `--user-timezone` converts times to the given IANA timezone.
- The reminder knob (`--reminder-on`/`--reminder-off`/`--reminder-minutes`) on `update` is Graph-only.
