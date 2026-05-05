---
name: imap-mail
description: Personal email via IMAP/SMTP with OAuth2. Read inbox, send mail, get notified on new mail. Works with Outlook/Hotmail/Microsoft 365 personal accounts and any provider that supports XOAUTH2 IMAP. Requires daemon.
---

# IMAP Mail

OAuth2-authenticated IMAP and SMTP for the user's personal email. Built around Microsoft personal accounts (`outlook.com`, `hotmail.com`, `live.com`) using Mozilla Thunderbird's public OAuth client ID, which is the standard workaround for an OS that has shut tenantless app registrations down. Also works for any other provider that supports XOAUTH2 over IMAP/SMTP if you swap the client ID + scopes.

The skill ships three commands:

- `imap-mail list-folders / list / get / search` for read access
- `imap-mail-send` for outbound mail (via SMTP XOAUTH2)
- A poll daemon that watches `INBOX` and writes a notification JSON to `~/agent/notifications/` on every new message, so the agent gets paged in real time

The daemon uses the same token cache and refreshes it transparently, so once the user has done the device flow once they don't need to re-auth for ~90 days.

**Setup**: see [SETUP.md](SETUP.md). It walks the device-flow login that gets the long-lived refresh token. Setup is one-time, takes ~2 minutes.

## Why XOAUTH2 + Thunderbird's client ID

Microsoft killed basic-auth IMAP for personal accounts in late 2024, and tenantless Azure app registrations were deprecated mid-2025. So the only OAuth2 path for a personal Microsoft account that doesn't require the user to register an Azure tenant is to reuse a published public OAuth client ID. Thunderbird's is `9e5f94bc-e8a4-4e73-b8be-63364c29d753`, baked into Thunderbird's source, and is the canonical "open-source mail client" choice many tools (mutt-with-xoauth2, getmail, mbsync wrappers, etc) use for the same reason. It's a public client ID, not a secret.

Scopes required:

- `https://outlook.office.com/IMAP.AccessAsUser.All`
- `https://outlook.office.com/SMTP.Send`

## Read commands

```bash
imap-mail list-folders
imap-mail list --folder INBOX --limit 20
imap-mail list --folder Sent --limit 50
imap-mail get --folder INBOX --uid 12345
imap-mail get --folder INBOX --uid 12345 --body-chars 8000
imap-mail search --folder INBOX --query 'FROM "stripe"'
imap-mail search --folder INBOX --query 'SUBJECT "wedding"'
imap-mail search --folder INBOX --query 'SINCE 1-Jan-2026'
```

`list` and `search` return JSON arrays of `{uid, from, to, subject, date}`. `get` returns the full message including a decoded plain-text body.

## Send

```bash
imap-mail-send --to "user@example.com" --subject "Hi" --body "first line\\nsecond line"
```

Sends as the configured user via SMTP STARTTLS XOAUTH2. The `From` header uses the configured display name + the user's email address.

## Notifications

The poll daemon (`screen -dmS imap-mail ... poll_daemon.py`) checks `INBOX` every 15s, tracks the highest UID seen, and writes one JSON file per new email into `~/agent/notifications/`. The notification has source `imap-mail`, type `email`, and includes `from`, `subject`, `date`, `uid`. The agent CLI picks it up the way it does any other notification source.

The daemon keeps a high-UID watermark at `$IMAP_MAIL_DIR/high_uid.txt`. First run seeds with the latest UID (no backlog flood); subsequent runs only emit new arrivals.

## Configuration

All paths and addresses are environment-driven so the skill is user-agnostic:

- `IMAP_MAIL_USER`: the email address (required, e.g. `nour.ataya@hotmail.co.uk`)
- `IMAP_MAIL_DIR`: where token + state live (default `~/.imap-mail`)
- `IMAP_MAIL_HOST`: IMAP host (default `outlook.office365.com`, port 993 SSL)
- `IMAP_MAIL_SMTP_HOST`: SMTP host (default `smtp.office365.com`, port 587 STARTTLS)
- `IMAP_MAIL_OAUTH_CLIENT_ID`: OAuth client ID (default Thunderbird's, used for personal Microsoft accounts)
- `IMAP_MAIL_OAUTH_AUTHORITY`: OAuth authority (default `https://login.microsoftonline.com/consumers` for personal accounts; switch to `/common` for mixed work+personal)
- `IMAP_MAIL_FROM_NAME`: display name on outbound mail (default the username portion of the email)
- `IMAP_MAIL_POLL_INTERVAL`: seconds between polls (default 15)

Set these in `~/.bashrc` so the daemon and CLI both see them.

## When NOT to use this skill

- The user has Gmail. Use the `google` skill (Gmail API is cleaner than IMAP).
- The user has a Microsoft 365 *work* account (a real Azure tenant). Use the `microsoft` skill (Graph API is more capable, calendars/contacts are included).
- The user wants an agent-owned inbox (no personal email). Use `agentmail`.

This skill is the right choice when the user has a personal Microsoft account (`@hotmail.com`, `@outlook.com`, `@live.com`) and wants the agent to read + send from it.
