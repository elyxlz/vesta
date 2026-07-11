---
name: microsoft
description: Outlook/Microsoft 365 work account via Graph: read/send/reply/forward email, drafts, flag/categorize, move/archive, folders, attachments, block senders, calendar and meetings, new-mail paging, and Microsoft Teams (chats, channels, presence, plus new-message notifications). Requires daemon.
---

# Microsoft - CLI: microsoft

**Setup / sign-in**: run **`microsoft auth setup --account <email>`**, one command provisions mail, calendar, and Teams and auto-picks device-code (personal / permissive) or a one-URL browser sign-in (locked work/school tenants), then auto-refreshes so the user signs in only once. Details and the two backends (Graph + browser-capture fallback): see [SETUP.md](SETUP.md).

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

### Cold-email screening (optional standing behavior)
If the user asks you to screen their inbox, watch new-mail notifications for **cold 1:1 outreach**: unsolicited investor/VC pitches, recruitment/mentor solicitations, sales/SaaS/agency prospecting, cold "let's chat" intros. For these:
- **Move the message to a `Screened` folder** on that account (`microsoft email move --account X --id <id> --to-folder Screened`) so it leaves the inbox, and **drop the notification** (never surface it).
- **Never delete** the Screened folder is a holding area the user can skim anytime; nothing real is lost.
- **When unsure, leave it in the inbox** (conservative: a genuine warm intro, a real deal, or anything from a known contact stays and gets surfaced normally). Better to leave one cold email than misfile a real one.
- **Repeat offenders → block the sender** (`microsoft email block --account X --sender ...`, Graph-only).
- Create the `Screened` folder once per account (`microsoft folder create --account X --name Screened`). Newsletters and marketing are usually better left in the inbox unless the user asks to file those too.

### Scheduling Preferences
[User's scheduling patterns. Fill in after data gathering: preferred meeting times, timezone, how they reschedule, buffer preferences]

### Regular Events
[Recurring meetings and commitments. Fill in after data gathering: weekly/monthly recurring events, who with]
