---
name: microsoft
description: Outlook email, inbox, calendar, meetings, events via Microsoft. Requires daemon.
---

# Microsoft - CLI: microsoft

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS microsoft microsoft serve --notifications-dir ~/agent/notifications`

## Three backends (Graph + OWA/EWS + OWA REST)

Every email and calendar command runs over one of three paths, chosen with
`--backend {auto,graph,owa,owa-rest}` (default `auto`):

- **`graph`**: the official Microsoft Graph API (`graph.microsoft.com`). The
  clean, supported path.
- **`owa`**: a reverse-engineered fallback that speaks Exchange Web Services
  (EWS) over a bearer token from the first-party "Microsoft Office" client. Works
  on locked-down tenants where Graph is unavailable (third-party apps blocked,
  Graph disabled, a missing delegated scope). Requires an interactive device-flow
  sign-in on first use.
- **`owa-rest`**: uses the OWA web app's own access token (captured from a live
  browser session via `microsoft auth owa-login`) to call the OWA REST API
  (`outlook.office.com/api/v2.0`). Path of last resort: works on tenants that
  block even the device-flow grant (e.g. universities requiring admin approval for
  all MSAL clients). Token is ~24 h; re-capture with a single command.
- **`auto`** (default): tries Graph; on a permission failure tries OWA/EWS; if
  EWS also fails and a REST token is on disk, falls back to REST. Non-permission
  errors propagate unchanged so fallbacks never hide real bugs.

**One-step OWA REST setup:**
```bash
microsoft auth owa-login --account you@company.com
```

**Path gaps:** attachments on send/draft/reply and recurring-event creation are
not yet implemented on EWS or REST paths (clear error raised). Inbox rules
(block/unblock) are Graph and EWS only; the REST path raises a clear error.

## Email

```bash
microsoft email list --account user@example.com
microsoft email get --account user@example.com --id <email_id>
microsoft email send --account user@example.com --to bob@example.com --subject "Hello" --body "Message"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks!"
microsoft email search --account user@example.com --query "project update"
```

## Email Block/Unblock

Block or unblock senders to filter unwanted emails:

```bash
microsoft email block --account user@example.com --sender spam@example.com
microsoft email unblock --account user@example.com --sender spam@example.com
microsoft email block --account user@example.com --list  # show blocked senders
```

After blocking a phishing/spam sender, clean up messages that already arrived:

```bash
microsoft email delete --account user@example.com --id <email_id>            # delete one message
microsoft email delete --account user@example.com --sender spam@example.com  # delete all from a sender
microsoft email delete --account user@example.com --sender spam@example.com --permanent  # hard delete
```

Delete soft-deletes to Deleted Items by default (moves to `deleteditems`); `--permanent` hard-deletes. `--id` and `--sender` are mutually exclusive and exactly one is required.

If block returns 403, re-authorize:
```bash
microsoft auth add --account user@example.com
```

## Calendar

```bash
microsoft calendar list --account user@example.com --days-ahead 7
microsoft calendar create --account user@example.com --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"
microsoft calendar respond --account user@example.com --id <event_id> --response accept
```

## Notes
- `--account` required for all email/calendar commands (find with: `microsoft auth list`)
- `--timezone` required for calendar create/update (IANA names like "Europe/London")
- `--response` choices: accept / decline / tentativelyAccept
- `--to`/`--cc`/`--attendees` accept multiple space-separated values
- `--no-cancellation` on delete skips notifying attendees
- `--no-details` on calendar list returns compact output (no body/attendees)
- `--user-timezone` on calendar list converts times to the given IANA timezone
- `--folder` on email list/search filters by folder (default "inbox")
- `--no-attachments` on email get skips attachment metadata
- `--save-to` on email get overrides the auto-save path for the body
- **`email get` always saves the body to disk** under `~/.microsoft/emails/<timestamp>_<subject>_<id>.txt` and strips it from the JSON response. The JSON returns `body: {saved_to, length, size_bytes, _note}` plus the legacy `body_saved_to`, `body_saved_size`, `body_length` fields, and a short `preview`. To inspect content, read the file at `body.saved_to`. The full `body.content` field is intentionally never returned inline to keep agent context small. Bodies over 5000 chars also surface a warning telling you to grep/crop before pasting snippets
- `--categories` on email update accepts multiple space-separated category names
- `email list`, `email search`, `calendar list`, and `calendar calendars` default to a compact tab-separated table; pass `--json` for one-line JSON or `--json-pretty` for indented JSON. Graph `@odata.*` metadata is stripped from every result.

## Email Attachments

```bash
microsoft email attachment --account user@example.com --email-id '<email_id>' --attachment-id '<attachment_id>' --save-path /tmp/file.pdf
```

### Contact Communication Styles
[How to communicate with different contacts. Fill in after data gathering: who are the key contacts, what tone/formality for each, language preferences]

### Email Preferences
[User's email patterns. Fill in after data gathering: greeting style, sign-offs, capitalization, punctuation habits, typical length, tone, which account for what]

### Scheduling Preferences
[User's scheduling patterns. Fill in after data gathering: preferred meeting times, timezone, how they reschedule, buffer preferences]

### Regular Events
[Recurring meetings and commitments. Fill in after data gathering: weekly/monthly recurring events, who with]
