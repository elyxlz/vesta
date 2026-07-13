---
name: email-client
description: Personal email over IMAP/SMTP for any provider (Gmail, Outlook, Yahoo, iCloud, Fastmail, generic IMAP). Multi-account: read an inbox, send/reply/forward, save drafts, manage messages and folders, handle attachments, and get paged on new mail. Gmail accounts also get Google Calendar (list/create/update/delete/respond to events) in the same sign-in. Requires the poll daemon for notifications.
---

# Email Client

Provider-agnostic IMAP/SMTP for the user's email accounts, any number side by side. Each account has its own credential, watermark, and notification stream. The provider is auto-detected from the email domain.

## When to use this skill

Use it for a uniform IMAP/SMTP interface across one or many personal accounts: read, send, reply, forward, manage, and get notified on new mail.

Google Calendar is also available here for Gmail accounts (see "Calendar" below): one Gmail sign-in grants both mail and calendar, so a lightweight calendar surface lives in this skill. Do not use it when the user wants the full Gmail API surface or Google contacts/Meet (use the `google` skill), a non-Google calendar or Graph/M365 *work* mail with IMAP/SMTP disabled (use the `microsoft` skill; M365 work *with* IMAP enabled works here, see SETUP.md "Microsoft 365 with a custom domain"), or an agent-owned inbox instead of personal mail (use `agentmail`).

## Notes & rules

Standing rules the user has given about how to handle their email live here. **Read this section at the start of every email task (and especially when processing a new-mail notification), and apply every rule that matches.** These rules override default behavior. (SETUP.md step 6 adds a MEMORY.md pointer reminding you to load this on every `email-client` notification.)

When the user states a durable rule or fact ("categorize every email from her as priority", "if an email mentions an invoice move it to Finance", "always draft a reply to everything in the Support folder", "my accountant is acct@example.com"), append it below using the Edit tool so it survives across sessions. Keep each entry to one line, prefix it with the account it applies to (or `[all]`), and write it as a **trigger → action** so it maps cleanly to the commands above. Update or delete an entry when the user changes or revokes it. Do not record one-off instructions for a single task, only durable rules.

How rules map to commands:

- *Categorize / prioritize by sender or content* → `mark --keyword <label>` (e.g. a `priority` keyword / Outlook category) or `mark --flagged`.
- *Route by content or sender* → `move --to-folder <folder>` (`archive` / `delete` for those destinations).
- *Auto-draft replies* → `email-client-send --reply-to-uid <uid> --draft` so the user reviews before it sends.
- *Suppress noise* → use `notify remove --folder <f>`, or note "don't surface" so you stay silent on matching mail.

Format: `- [account|all] when <trigger> → <action>`. Examples:

```text
- [work] when from boss@example.com → mark --keyword priority and notify me
- [personal] when subject/body mentions an invoice or receipt → move --to-folder Finance
- [all] when a new email lands in the Support folder → draft a reply (--draft) for review
- [work] when from noreply@* → auto-archive, do not notify
```

<!-- Agent: add the user's real rules below this line, one per line. The block above is illustrative; this list starts empty. -->

_(no rules recorded yet)_

## Setup

One-time per account, ~2 minutes. See [SETUP.md](SETUP.md) for install, every auth flow, and provider-specific notes. After `email-client auth add` runs once per account, no re-auth is needed until the refresh token expires (Microsoft ~90 days, Google until revoked) or the app password rotates.

Two binaries plus a daemon:

- `email-client` - read (`list-folders`, `list`, `get`, `search`, `attachments`, `status`), manage messages (`mark`, `move`, `archive`, `delete`), manage folders (`folder create/rename/delete/subscribe`), and choose notify folders (`notify list/add/remove`)
- `email-client-send` - outbound mail (send, reply, forward, save draft)
- `poll_daemon.py` - watches each account's chosen folders (INBOX by default) and writes a notification per new message

Omit `--account` on any command to use the default account from `accounts.json`. All commands accept `--account` and (where relevant) `--folder` (default `INBOX`).

## Read

```bash
email-client list-folders --account personal
email-client list --account personal --folder INBOX --limit 20
email-client list --account work --folder Sent --limit 50
email-client get --account personal --folder INBOX --uid 12345
email-client get --account personal --folder INBOX --uid 12345 --body-chars 8000
email-client search --account work --folder INBOX --query 'FROM "billing@example.com"'
email-client search --account personal --folder INBOX --query 'SUBJECT "invoice"'
email-client search --account personal --folder INBOX --query 'SINCE 1-Jan-2026'
```

`list` and `search` return JSON arrays of `{uid, from, to, subject, date}`. `get` returns the full message including a decoded plain-text body. `search --query` takes a raw IMAP SEARCH expression.

## Attachments

```bash
email-client attachments --uid 12345                              # list only
email-client attachments --uid 12345 --folder Archive             # different folder
email-client attachments --uid 12345 --download                   # save all
email-client attachments --uid 12345 --download --out-dir /tmp/x  # custom dir
email-client attachments --uid 12345 --download --part 2          # one specific
```

## Folder counts

```bash
email-client status --folder INBOX            # counts without fetching
email-client status --folder Archive --account work
```

Returns `{folder, messages, unseen, recent, uidnext, uidvalidity}` via IMAP `STATUS` - far cheaper than `list` when you only need "how many unread". Loop over folders from `list-folders` for a full overview.

## Manage messages

```bash
email-client mark --uid 12345 --read
email-client mark --uid 12345 --unread
email-client mark --uid 12,15,18 --flagged
email-client mark --uid 12 --unflagged --account work
email-client mark --uid 12345 --answered            # \Answered (replied-to indicator)
email-client mark --uid 12345 --draft               # \Draft
email-client mark --uid 12345 --keyword Receipts     # custom keyword (= Outlook category)
email-client mark --uid 12345 --keyword Tax --keyword Receipts
email-client mark --uid 12345 --unkeyword Receipts
email-client move --uid 12345 --to-folder Archive
email-client archive --uid 12345
email-client delete --uid 12345                # soft delete to Deleted (recoverable)
email-client delete --uid 12345 --hard         # permanently expunge
```

## Manage folders

```bash
email-client folder create --name Parent/Child         # nest with the server delimiter
email-client folder rename --name OldName --to-name NewName
email-client folder delete --name Parent/Child
email-client folder subscribe --name Newsletters
email-client folder subscribe --name Newsletters --unsubscribe
```

`create` makes a new mailbox (nest using the server's hierarchy delimiter, usually `/` or `.` - check `list-folders`). `move --to-folder X` fails if `X` doesn't exist, so create it first. `subscribe` toggles whether a folder appears in clients that only show subscribed mailboxes. All honor `--account`.

## Send

```bash
email-client-send --account personal --to "recipient@example.com" --subject "Hi" --body "first line\\nsecond line"
email-client-send --account personal --to recipient@example.com --cc cc1@example.com --cc cc2@example.com --subject "Hi" --body "team note"
email-client-send --account personal --to recipient@example.com --bcc bcc@example.com --subject "Quiet ping" --body "fyi"
email-client-send --account personal --to recipient@example.com --subject "Hi" --body "plain fallback" --body-html "<p>rich <b>HTML</b></p>"
email-client-send --account personal --to recipient@example.com --subject "Slides" --body "see attached" --attach ~/file.pdf
email-client-send --account personal --to recipient@example.com --subject "Pics" --body "two of them" --attach first.png --attach second.jpg
```

Repeat `--cc` / `--bcc` / `--attach` for multiple values. `--body-html` sends HTML (combine with `--body` for multipart/alternative, or pass it alone for a synthesized plain-text fallback). Attachments are capped at 25 MB total; the send aborts with a clear error past that, since most providers reject larger.

After a successful send the message is IMAP-APPENDed (with attachments) to the Sent folder so it shows in the user's mail UI. Skip with `--no-sent-sync`. The Sent folder is auto-detected from the server's RFC 6154 SPECIAL-USE attribute (`\Sent`), falling back to the provider profile's `sent_folder` then `Sent` - so it works even when a server names the folder unusually.

### Reply

```bash
email-client-send --account personal --reply-to-uid 12345 --body "thanks, will do"
email-client-send --account personal --reply-to-uid 12345 --body "ack" --no-quote
email-client-send --account work --reply-folder Archive --reply-to-uid 999 --body "looking now" --dry-run
email-client-send --account personal --reply-to-uid 12345 --to "other@example.com" --body "looping in another recipient"
email-client-send --account personal --reply-to-uid 12345 --cc cc1@example.com --body "adding a cc recipient"
```

Pass `--reply-to-uid <uid>` (and `--reply-folder <folder>` if the original isn't in `INBOX`). The skill fetches the original from the same account and:

- threads via `In-Reply-To` and `References` (preserving the chain)
- defaults the subject to `Re: <original>` (no double prefix)
- defaults `--to` to the original sender
- preserves the original `Cc` unless you pass `--cc` (then your list wins)
- appends a quoted original below an `On <date>, <from> wrote:` separator

Override any default by passing the flag explicitly. `--no-quote` drops the quoted body; `--dry-run` prints the would-send message without contacting SMTP. After a real (non-dry-run) reply sends, the original message is flagged `\Answered` so every client shows the replied-to indicator (non-fatal if it can't be set).

### Forward

```bash
email-client-send --account personal --forward-uid 12345 --to recipient@example.com --body "fyi, see below"
email-client-send --account work --forward-uid 999 --forward-folder Archive --to recipient@example.com --body "" --no-quote
```

Pass `--forward-uid <uid>` (and `--forward-folder` if not in `INBOX`). `--to` is required. Defaults the subject to `Fwd: <original>` (no double prefix), inlines the original headers and body below your `--body`, and starts a new thread (no `In-Reply-To`/`References`). `--no-quote` suppresses the inlined original.

### Drafts

Pass `--draft` to save the composed message to the Drafts folder (flagged `\Draft`) instead of sending it. It accepts the full compose surface: `--cc`/`--bcc`, `--body-html`, `--attach` - and crucially `--reply-to-uid` / `--forward-uid`, so you can draft a threaded reply or forward for the user to review and send from any mail client.

```bash
email-client-send --account personal --to recipient@example.com --subject "Proposal" --body "rough notes..." --draft
email-client-send --account personal --reply-to-uid 12345 --body "draft answer for you to review" --draft
email-client-send --account personal --forward-uid 999 --to recipient@example.com --body "fyi" --draft
```

A draft does not contact SMTP and does not flag the original `\Answered` (nothing was sent). `--dry-run` previews the draft without writing it. The Drafts folder is auto-detected (see below).

### Draft-only mode

Set `EMAIL_DRAFT_ONLY=1` (truthy: `1`/`true`/`yes`, case-insensitive) to **hard-disable sending**. In this mode any send/reply/forward invocation is refused before touching SMTP (non-zero exit with a clear message); `--draft` (and `--dry-run` preview) still work. This is a CLI-level safety guarantee, not a behavioral promise. Default off: unset/empty means today's behavior, no change.

## Calendar (Gmail accounts only)

Google Calendar rides the same Gmail sign-in: one consent grants mail and calendar together (the reused verified Thunderbird client bundles `https://www.googleapis.com/auth/calendar`), so there is no separate Google app, no verification, and no CASA. These commands reuse the account's stored Google token (with the same transparent refresh as mail) and call the Google Calendar REST API v3. They only work on Google accounts; on any other provider they exit with a clear "only supported for Google accounts" error.

```bash
email-client calendar list-calendars --account personal
email-client calendar list --account personal --days-ahead 14 --days-back 1
email-client calendar get --account personal --id <eventId>
email-client calendar create --account personal --subject "Design sync" --start 2026-07-20T15:00:00 --end 2026-07-20T16:00:00 --attendees a@x.com,b@y.com --location "Room 1" --timezone Europe/London
email-client calendar update --account personal --id <eventId> --start 2026-07-20T16:00:00 --end 2026-07-20T17:00:00 --timezone Europe/London
email-client calendar delete --account personal --id <eventId>
email-client calendar respond --account personal --id <eventId> --response accept   # accept|decline|tentative
```

`--calendar` defaults to `primary` on every command; pass a calendar id (from `list-calendars`) to target a shared or secondary calendar. `list` returns a JSON array of `{id, summary, start, end, location, attendees, status}` over the window (default: next 7 days). `create` defaults `--end` to one hour after `--start` for timed events, or the next day for all-day events (a date with no `T`); `--timezone` defaults to UTC. `--attendees` accepts a comma-separated list and is repeatable. `update` requires `--timezone` whenever you change `--start` or `--end`.

**Invites are a real send.** Creating or updating an event that has attendees makes Google email them a calendar invite or update (and `delete` sends a cancellation). That is an outward action just like sending mail, so treat it with the same care. Note that `EMAIL_DRAFT_ONLY` guards *email* sending only; it does **not** block calendar writes, so use judgment before creating or updating events with attendees.

**Re-auth for existing accounts.** Any Gmail account added before this feature must re-auth once to grant the calendar scope (and to move to the corrected client id): `email-client auth add --account <name> --provider gmail --reauth`. Freshly added accounts get mail and calendar in one sign-in. A calendar command that reports a scope error means the token predates calendar support: re-auth as above.

## Account management

```bash
email-client auth add --account personal              # auto-detect provider from email
email-client auth add --account work --provider gmail # force a provider
email-client auth list                                # JSON array of registered accounts
email-client auth remove --account old
```

The first added account becomes the default. To change it, edit `default` in `$EMAIL_CLIENT_DIR/accounts.json`.

## Notifications

Start the poll daemon with `email-client daemon start` (see SETUP.md); manage it only through `email-client daemon start|stop|restart|status`, never raw `screen` or signals. Start is idempotent (never stacks a duplicate daemon); `daemon status` reports process state and per-account auth health in one JSON blob, so there's no need to `screen -X hardcopy` or read the log by hand.

The daemon runs one worker per **(account, folder)** being watched, each holding a persistent IMAP connection. Where the server advertises **IDLE** (Gmail, Microsoft, most others), the worker gets pushed on new mail in real time; otherwise it falls back to polling every `--interval` seconds (default 15). Either way it writes one JSON per new email into `~/agent/notifications/`. Each notification has source `email-client`, type `email`, `account` and `folder` fields, and `from`, `subject`, `date`, `uid`. The agent picks it up like any other notification source. If the daemon dies unexpectedly it writes a `daemon_died` notification with a `reason`; a deliberate `daemon stop`/`restart` never does.

### Choosing which folders notify

By default the daemon watches only `INBOX` per account. To watch more folders (or fewer), set the per-account watch list; the daemon picks up changes within ~10s, no restart needed:

```bash
email-client notify list                              # show watched folders
email-client notify add --all                         # subscribe to every folder
email-client notify add --folder Archive              # also notify on Archive
email-client notify add --folder "[Gmail]/Important" --account work
email-client notify remove --folder INBOX             # stop notifying on INBOX
```

`notify add --folder` validates the folder exists on the server before saving; `notify add --all` replaces the watch list with every folder on the server (handy as a default, but it includes noisy ones like Sent/Spam/Trash; prune with `notify remove`). Removing every folder mutes the account. The watch list lives in `accounts/<name>/config.json` under `notify_folders`.

State layout, the full environment-variable list, and Microsoft 365 custom-domain setup live in [SETUP.md](SETUP.md).
