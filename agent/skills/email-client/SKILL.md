---
name: email-client
description: Personal email via IMAP/SMTP for any provider (Gmail, Outlook/Hotmail/Microsoft personal, Yahoo, iCloud, Fastmail, generic IMAP). Multi-account. Use to read an inbox, send/reply/forward mail, save drafts, manage messages (read/flag/answered/draft/categories, move/archive/delete), create/rename/delete folders, check folder counts, handle attachments, or get paged on new mail in real time (IMAP IDLE) from chosen folders. OAuth2 where supported, app-password fallback otherwise. Requires the poll daemon for notifications.
---

# Email Client

Provider-agnostic IMAP/SMTP for the user's  email accounts, any number side by side. Each account has its own credential, watermark, and notification stream. The provider is auto-detected from the email domain.

## When to use this skill

Use it for a uniform IMAP/SMTP interface across one or many personal accounts: read, send, reply, forward, manage, and get notified on new mail.

Do NOT use it when:

- The user wants the full Gmail API surface (labels, threads, drafts as Google models them) → use the `google` skill.
- The user has an M365 *work* account with IMAP/SMTP disabled, or wants calendar/contacts/Graph → use the `microsoft` skill. (M365 work accounts *with* IMAP enabled work here; see "Microsoft 365 with a custom domain".)
- The user wants an agent-owned inbox rather than their personal mail → use `agentmail`.

## Notes & rules

Standing rules the user has given about how to handle their email live here. **Read this section at the start of every email task — and especially when processing a new-mail notification — and apply every rule that matches.** These rules override default behavior. (Setup adds a pointer in `~/agent/MEMORY.md` reminding you to load and apply this section on every `email-client` notification — see SETUP.md step 6.)

When the user states a durable rule or fact ("categorize every email from her as priority", "if an email mentions an invoice move it to Finance", "always draft a reply to everything in the Support folder", "my accountant is acct@example.com"), append it below using the Edit tool so it survives across sessions. Keep each entry to one line, prefix it with the account it applies to (or `[all]`), and write it as a **trigger → action** so it maps cleanly to the commands above. Update or delete an entry when the user changes or revokes it. Do not record one-off instructions for a single task — only durable rules.

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

- `email-client` — read (`list-folders`, `list`, `get`, `search`, `attachments`, `status`), manage messages (`mark`, `move`, `archive`, `delete`), manage folders (`folder create/rename/delete/subscribe`), and choose notify folders (`notify list/add/remove`)
- `email-client-send` — outbound mail (send, reply, forward, save draft)
- `poll_daemon.py` — watches every account's `INBOX` and writes a notification per new message

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

Listing returns `{part_index, name, content_type, size_bytes}` per attachment. A part counts as an attachment when it has `Content-Disposition: attachment`, OR a filename, OR is an inline `image/*` with a name; plain-text and HTML body parts are excluded unless explicitly tagged as attachments.

`--download` writes to `$EMAIL_CLIENT_DIR/attachments/<uid>/` (override with `--out-dir`). `--part <index>` saves a single attachment using its `part_index` from the listing. Filenames are sanitized and de-duplicated; saved paths print as JSON.

## Folder counts

```bash
email-client status --folder INBOX            # counts without fetching
email-client status --folder Archive --account work
```

Returns `{folder, messages, unseen, recent, uidnext, uidvalidity}` via IMAP `STATUS` — far cheaper than `list` when you only need "how many unread". Loop over folders from `list-folders` for a full overview.

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

All accept comma-separated UIDs and combine flags in one call. `mark` sets/clears the IMAP system flags `\Seen` (`--read`/`--unread`), `\Flagged` (`--flagged`/`--unflagged`), `\Answered` (`--answered`/`--unanswered`), `\Draft` (`--draft`/`--undraft`), and arbitrary keywords (`--keyword`/`--unkeyword`, both repeatable). A custom keyword is how Outlook stores **Categories**, so `--keyword Receipts` tags a message in a way Outlook surfaces as a category. `\Flagged` shows as a star in Gmail and a flag in Apple Mail/Outlook. `move` uses IMAP `MOVE` when advertised, else `COPY` + `STORE +Deleted` + `EXPUNGE`. `archive` and `delete` (soft) auto-detect their destination from the server's RFC 6154 SPECIAL-USE attributes (`\Archive`, `\Trash`), falling back to `Archive` / `Deleted`; `delete --hard` expunges in place. Soft-delete lets the user recover from trash. All of these are server-side and sync to every client on the account.

## Manage folders

```bash
email-client folder create --name Parent/Child         # nest with the server delimiter
email-client folder rename --name OldName --to-name NewName
email-client folder delete --name Parent/Child
email-client folder subscribe --name Newsletters
email-client folder subscribe --name Newsletters --unsubscribe
```

`create` makes a new mailbox (nest using the server's hierarchy delimiter, usually `/` or `.` — check `list-folders`). `move --to-folder X` fails if `X` doesn't exist, so create it first. `subscribe` toggles whether a folder appears in clients that only show subscribed mailboxes. All honor `--account`.

## Send

```bash
email-client-send --account personal --to "recipient@example.com" --subject "Hi" --body "first line\\nsecond line"
email-client-send --account personal --to recipient@example.com --cc cc1@example.com --cc cc2@example.com --subject "Hi" --body "team note"
email-client-send --account personal --to recipient@example.com --bcc bcc@example.com --subject "Quiet ping" --body "fyi"
email-client-send --account personal --to recipient@example.com --subject "Hi" --body "plain fallback" --body-html "<p>rich <b>HTML</b></p>"
email-client-send --account personal --to recipient@example.com --subject "Slides" --body "see attached" --attach ~/file.pdf
email-client-send --account personal --to recipient@example.com --subject "Pics" --body "two of them" --attach first.png --attach second.jpg
```

Sends as the configured user for the account. The `From` header uses the configured display name + the user's address. OAuth providers use SMTP STARTTLS XOAUTH2; app-password providers use plain LOGIN over STARTTLS.

- `--cc` / `--bcc`: repeat the flag for multiple addresses.
- `--body-html`: send HTML. Combine with `--body` for multipart/alternative; pass `--body-html` alone and a plain-text fallback is synthesized.
- `--attach <path>`: repeat for multiple. MIME type guessed by extension (fallback `application/octet-stream`). Total capped at 25 MB — the send aborts with a clear error past that, since most providers reject larger.

After a successful send the message is IMAP-APPENDed (with attachments) to the Sent folder so it shows in the user's mail UI. Skip with `--no-sent-sync`. The Sent folder is auto-detected from the server's RFC 6154 SPECIAL-USE attribute (`\Sent`), falling back to the provider profile's `sent_folder` then `Sent` — so it works even when a server names the folder unusually.

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

Pass `--draft` to save the composed message to the Drafts folder (flagged `\Draft`) instead of sending it. It accepts the full compose surface — `--cc`/`--bcc`, `--body-html`, `--attach` — and crucially `--reply-to-uid` / `--forward-uid`, so you can draft a threaded reply or forward for the user to review and send from any mail client.

```bash
email-client-send --account personal --to recipient@example.com --subject "Proposal" --body "rough notes..." --draft
email-client-send --account personal --reply-to-uid 12345 --body "draft answer for you to review" --draft
email-client-send --account personal --forward-uid 999 --to recipient@example.com --body "fyi" --draft
```

A draft does not contact SMTP and does not flag the original `\Answered` (nothing was sent). `--dry-run` previews the draft without writing it. The Drafts folder is auto-detected (see below).

## Account management

```bash
email-client auth add --account personal              # auto-detect provider from email
email-client auth add --account work --provider gmail # force a provider
email-client auth list                                # JSON array of registered accounts
email-client auth remove --account old
```

The first added account becomes the default. To change it, edit `default` in `$EMAIL_CLIENT_DIR/accounts.json`.

## Notifications

Start the poll daemon (see SETUP.md). It runs one worker per **(account, folder)** being watched, each holding a persistent IMAP connection. Where the server advertises **IDLE** (Gmail, Microsoft, most others), the worker gets pushed on new mail in real time; otherwise it falls back to polling every `--interval` seconds (default 15). Either way it writes one JSON per new email into `~/agent/notifications/`. Each notification has source `email-client`, type `email`, `account` and `folder` fields, and `from`, `subject`, `date`, `uid`. The agent picks it up like any other notification source.

### Choosing which folders notify

By default the daemon watches only `INBOX` per account. To watch more folders (or fewer), set the per-account watch list — the daemon picks up changes within ~10s, no restart needed:

```bash
email-client notify list                              # show watched folders
email-client notify add --folder Archive              # also notify on Archive
email-client notify add --folder "[Gmail]/Important" --account work
email-client notify remove --folder INBOX             # stop notifying on INBOX
```

`notify add` validates the folder exists on the server before saving. Removing every folder mutes the account. The watch list lives in `accounts/<name>/config.json` under `notify_folders`.

The supervisor recomputes the watch set periodically and starts/stops workers as accounts or folders change. Each watched `(account, folder)` keeps its own watermark (`high_uid.txt` for INBOX, `high_uid_<folder>.txt` otherwise); the first run for a folder seeds it with the latest UID to avoid a backlog flood, and later runs emit only new arrivals. Filenames look like `email-client-personal-INBOX-1746480000000-abc123.json` so concurrent notifications never collide. Workers reconnect on error and on a periodic refresh so the OAuth access token stays current.

## State layout

```
$EMAIL_CLIENT_DIR/                # default ~/.email-client
  accounts.json                   # {"accounts": ["personal","work"], "default": "personal"}
  accounts/
    personal/
      config.json                 # {"user", "provider", optional host overrides, "notify_folders"}
      token.json                  # OAuth token or {"app_password": "..."} (mode 600)
      high_uid.txt                # INBOX watermark
      high_uid_Archive.txt        # per-folder watermark (one per extra watched folder)
    work/ ...
```

`token.json` always carries a `provider` key alongside the credential (access/refresh token for OAuth, `app_password` otherwise), so the daemon knows the auth strategy even if env vars change later.

## Configuration

Settings live per account in `accounts/<name>/config.json`. Env vars provide defaults applied to whichever account is in use:

- `EMAIL_CLIENT_DIR` — token + state location (default `~/.email-client`)
- `EMAIL_CLIENT_USER` — default email address (used at `auth add` when `--user` is omitted)
- `EMAIL_CLIENT_PROVIDER` — default provider key
- `EMAIL_CLIENT_HOST` — IMAP host override
- `EMAIL_CLIENT_SMTP_HOST` / `EMAIL_CLIENT_SMTP_PORT` — SMTP host / port (default 587 STARTTLS)
- `EMAIL_CLIENT_OAUTH_CLIENT_ID` — OAuth client ID override
- `EMAIL_CLIENT_OAUTH_AUTHORITY` — Microsoft authority override (e.g. `/common` for mixed work+personal)
- `EMAIL_CLIENT_OAUTH_SCOPES` — whitespace-separated scope override
- `EMAIL_CLIENT_FROM_NAME` — display name on outbound mail (default: username portion of the email)
- `EMAIL_CLIENT_POLL_INTERVAL` — seconds between polls (default 15)
- `EMAIL_CLIENT_APP_PASSWORD` — pre-supply the app password to `auth add` instead of prompting (for scripts)

## Microsoft 365 with a custom domain

For an address on a custom domain hosted by M365 (e.g. `you@yourcompany.com`, mailbox on Exchange Online), use the `generic` provider:

```bash
export EMAIL_CLIENT_PROVIDER=generic
export EMAIL_CLIENT_OAUTH_CLIENT_ID=9e5f94bc-e8a4-4e73-b8be-63364c29d753   # Thunderbird, multi-tenant
export EMAIL_CLIENT_OAUTH_AUTHORITY=https://login.microsoftonline.com/common
export EMAIL_CLIENT_HOST=outlook.office365.com
export EMAIL_CLIENT_SMTP_HOST=smtp.office365.com
email-client auth add --account work --provider generic --user you@yourcompany.com
```

Approve the device-flow code at https://www.microsoft.com/link. Three org-side blockers can stop this (none fixable from the skill):

1. **Third-party OAuth clients disabled** → device flow returns `AADSTS50020` / "needs admin consent". Fix: admin registers an internal Azure app with `Mail.ReadWrite` + `SMTP.Send` delegated permissions; set `EMAIL_CLIENT_OAUTH_CLIENT_ID` to it.
2. **IMAP/SMTP disabled on the mailbox** → `LOGIN`/`AUTHENTICATE` fails after a successful OAuth. Fix: admin runs `Set-CASMailbox -ImapEnabled $true`, or switch to the `microsoft` (Graph) skill.
3. **Conditional Access policies** → device flow lands on "your sign-in was blocked". Fix: admin must whitelist the app or relax the policy. No client-side workaround.

If 1–3 all check out and it still fails, capture the full error from `email-client auth add --reauth`; the useful detail is usually in the OAuth response's `error_description`.
