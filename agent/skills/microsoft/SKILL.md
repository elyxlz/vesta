---
name: microsoft
description: Outlook/Microsoft 365 work account via Graph: read/send/reply/forward email, drafts, flag/categorize, move/archive, folders, attachments, block senders, calendar and meetings, new-mail paging, and Microsoft Teams (chats, channels, presence, plus new-message notifications). Requires daemon.
---

# Microsoft - CLI: microsoft

**Setup, sign-in, and the two backends** (Graph + browser-capture fallback for locked tenants): see [SETUP.md](SETUP.md). **Ask the user whether the account is personal or work/school before signing in**: personal accounts use device-code flow, work/school accounts on a locked tenant use browser capture (needs no admin consent).

**Background daemon**: `screen -dmS microsoft microsoft serve --notifications-dir ~/agent/notifications`

## Command groups

Each area's detail lives in its own file, read it when you work in that area:

- **Email**: read/send/reply/forward, search, organize (flag/categorize/move/archive), drafts, folders, block/unblock, attachments. See [references/email.md](references/email.md).
- **Calendar**: list/create/update/respond to events and meetings. See [references/calendar.md](references/calendar.md).
- **Teams**: chats, channels, presence (and Teams sign-in). See [references/teams.md](references/teams.md).
- **Notifications**: new-mail folder watching + Teams chat alerts. See [references/notifications.md](references/notifications.md).

## Shared flags

- `--account <email>` is required on every email/calendar/folder/teams command (list accounts with `microsoft auth list`; sign one out with `microsoft auth remove --account <email>`).
- `--backend {auto,graph,owa-rest}` (default `auto`) picks the path; both backends support the full surface except `block`/`unblock` (Graph-only). See [SETUP.md](SETUP.md).
- List commands (`email list`/`search`, `calendar list`/`calendars`, `folder list`, `teams chats`/`messages`/`teams`/`channels`) default to a compact tab-separated table; pass `--json` for one-line JSON or `--json-pretty` for indented JSON. Graph `@odata.*` metadata is stripped from every result.

## Personalization

### Contact Communication Styles
[How to communicate with different contacts. Fill in after data gathering: who are the key contacts, what tone/formality for each, language preferences]

### Email Preferences
[User's email patterns. Fill in after data gathering: greeting style, sign-offs, capitalization, punctuation habits, typical length, tone, which account for what]

### Scheduling Preferences
[User's scheduling patterns. Fill in after data gathering: preferred meeting times, timezone, how they reschedule, buffer preferences]

### Regular Events
[Recurring meetings and commitments. Fill in after data gathering: weekly/monthly recurring events, who with]
