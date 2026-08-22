---
name: microsoft
description: Use for any Microsoft account, personal or work (Outlook.com, Hotmail, Live, Microsoft 365); preferred over email-client for Microsoft accounts. Graph-based mail (read/send/reply/forward, drafts, flag/categorize, move/archive, folders, attachments, block senders), calendar and meetings, Microsoft Teams (chats, channels, presence), and new-mail/Teams notifications. Requires daemon.
---

# Microsoft - CLI: microsoft

**Setup / sign-in**: run **`microsoft auth setup --account <email>`**, one command provisions mail, calendar, and Teams and auto-picks device-code (personal / permissive) or a one-URL browser sign-in (locked work/school tenants), then auto-refreshes so the user signs in only once. Details and the two backends (Graph + browser-capture fallback): see [SETUP.md](SETUP.md).

**Background daemon**: `microsoft daemon start`

## Command groups

Each area's detail lives in its own file, read it when you work in that area:

- **Email**: read/send/reply/forward, search, organize (flag/categorize/move/archive), drafts, folders, block/unblock, attachments. See [references/email.md](references/email.md).
- **Calendar**: list/create/update/respond to events and meetings. See [references/calendar.md](references/calendar.md).
- **Teams**: chats, channels, presence (and Teams sign-in). See [references/teams.md](references/teams.md).
- **Notifications**: new-mail folder watching + Teams chat alerts (plus non-interrupting Teams channel alerts where the account has channel access; degrades to chats-only otherwise). See [references/notifications.md](references/notifications.md).

## Shared flags

- `--account <email>` is required on mailbox/calendar/folder/teams commands. Client-wide `email send-delay`, `email pending`, and `email undo` are the exceptions; `email pending` accepts an optional account filter. List accounts with `microsoft auth list`; sign one out with `microsoft auth remove --account <email>`.
- `--backend {auto,graph,owa-rest}` (default `auto`) picks the path for mailbox operations; both backends support the full surface except `block`/`unblock` (Graph-only). Delayed-send management does not take this flag. See [SETUP.md](SETUP.md).
- List commands (`email list`/`search`, `calendar list`/`calendars`, `folder list`, `teams chats`/`messages`/`teams`/`channels`) default to a compact tab-separated table; pass `--json` for one-line JSON or `--json-pretty` for indented JSON. Graph `@odata.*` metadata is stripped from every result.
- **`email search` is not evidence that a message never arrived**: it returned unrelated results for the exact subject of a message known to be sitting in **JunkEmail**. A query for a sender address returns that sender's messages top-ranked, so the tool itself works. Whether Junk is out of search scope, ranked out, or indexed late is not established, and the guidance is the same either way: **to check Junk, LIST it (`email list --folder JunkEmail`), never search for it.** Some senders land there consistently, so a search-based negative is wrong twice over.
- `email list`/`search` take `--since YYYY-MM-DD` / `--until YYYY-MM-DD` (both inclusive) to reach mail by date. Plain `search` uses relevance-ranked `$search`, which buries old mail; the date flags switch to a `receivedDateTime` range filter ordered newest-first. See [references/email.md](references/email.md).

## Draft-only mode

Set `EMAIL_DRAFT_ONLY=1` (truthy: `1`/`true`/`yes`, case-insensitive) to **hard-disable sending**. In this mode `email send`/`reply`/`forward` are refused before any Graph or OWA-REST call (non-zero exit with a clear message); only `email draft` works. This is a CLI-level safety guarantee, not a behavioral promise, and it covers **both** backends. Default off: unset/empty means today's behavior, no change.

Set `MICROSOFT_READ_ONLY=1` (same truthy values) to make **every connected account read-only**. This is the stronger setting and the right one when the account belongs to someone who did not ask you to act on their behalf, e.g. a work mailbox you were given so you could read it. It refuses every command that writes: `email send`/`reply`/`forward`/`draft`/`reply-draft`/`move`/`archive`/`update`/`delete`/`block`/`unblock`, `calendar create`/`update`/`delete`/`respond`, `folder create`/`rename`/`delete`, `teams send`/`start`/`post`/`reply`/`set-presence`/`clear-presence`, and `notify add`/`remove`. Reads are untouched.

The refusal happens in the CLI before any Graph or OWA-REST call, so it covers both backends. Still allowed on purpose: `email send-delay` and `email pending` configure and inspect the **local** outbox and are invisible to the account's owner, and `email undo` only ever cancels a queued send. Default off: unset/empty leaves every command allowed.

## Personalization

## Threaded reply DRAFT (leave unsent for the user to send)

`email reply` ALWAYS sends and `email draft --reply-to` overwrites the quoted history. To leave a
threaded reply(-all) draft the user reviews + sends themselves, use `email reply-draft`
(createReply/createReplyAll + body placed above the preserved quote + attach, no /send):

```bash
microsoft email reply-draft --account user@example.com --id '<latest-msg-id-in-thread>' --body "draft answer for review"
microsoft email reply-draft --account user@example.com --id '<email_id>' --body "thanks all" --reply-all --attachments /path/file.pdf
```

`--body` is plain text (`- ` lines become bullets), placed above the quoted thread. On a re-edit
pass `--replace-draft <old_id>` (the `id` printed by the prior run) so repeated tweaks leave
exactly one draft, not a pile. Graph-only.

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
