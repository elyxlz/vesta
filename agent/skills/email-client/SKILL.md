---
name: imap-mail
description: Personal email via IMAP/SMTP for any provider (Gmail, Outlook/Hotmail/Microsoft personal, Yahoo, iCloud, Fastmail, generic IMAP). Read inbox, send mail, get notified on new mail. OAuth2 where supported, app-password fallback otherwise. Requires daemon.
---

# IMAP Mail

Provider-agnostic IMAP and SMTP for the user's personal email. Supports:

- **Microsoft personal** (`outlook.com`, `hotmail.com`, `live.com`) via OAuth2 device flow + Mozilla Thunderbird's public client ID
- **Gmail** via OAuth2 loopback flow + Thunderbird's public Google client ID
- **Yahoo Mail** via app password
- **iCloud Mail** via app password
- **Fastmail** via app password
- **Generic IMAP/SMTP** (any host, any auth) via env-driven config

The provider is auto-detected from the user's email domain. Override with the `--provider` flag on `auth.py` or `IMAP_MAIL_PROVIDER` in the environment.

The skill ships three commands:

- `imap-mail list-folders / list / get / search` for read access
- `imap-mail-send` for outbound mail
- A poll daemon that watches `INBOX` and writes a notification JSON to `~/agent/notifications/` on every new message, so the agent gets paged in real time

The daemon shares the same token cache and refreshes OAuth access tokens transparently. Once the user has run `auth.py` once, no re-auth is needed for the lifetime of the refresh token (Microsoft ~90 days, Google effectively until revoked) or until the app password is rotated.

**Setup**: see [SETUP.md](SETUP.md). It covers all auth strategies and walks each one end to end. Setup is one-time, takes about 2 minutes.

## Why XOAUTH2 + Thunderbird's client IDs

Microsoft killed basic-auth IMAP for personal accounts in late 2024, and tenantless Azure app registrations were deprecated mid-2025. So the only OAuth2 path for a personal Microsoft account that doesn't require the user to register an Azure tenant is to reuse a published public OAuth client ID. Thunderbird's Microsoft client ID is `9e5f94bc-e8a4-4e73-b8be-63364c29d753`, baked into Thunderbird's source, and is the canonical "open-source mail client" choice many tools (mutt-with-xoauth2, getmail, mbsync wrappers, etc) use for the same reason.

Google's situation is similar but with one twist: Google deprecated OAuth device flow for non-TV/non-input-constrained desktop apps, so the supported equivalent is the loopback redirect flow (`http://127.0.0.1:<port>/`). This skill spins up a tiny `http.server` on a random port, opens (or prints) the consent URL, and captures the authorization code from the redirect. Thunderbird's Google client ID is `406964657835-aq8lmia8j95dhl1a2bvharmfk3t1glqf.apps.googleusercontent.com`.

Both client IDs are public, not secrets.

For Yahoo, iCloud, Fastmail, and generic IMAP, the providers expose either no OAuth or no public client at all, so we fall back to **app passwords**: the user generates a one-off password in their account security settings and we store it (chmod 600). Yahoo/iCloud both warn the user this is normal for "less secure apps".

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

Sends as the configured user. OAuth providers use SMTP STARTTLS XOAUTH2; app-password providers use plain LOGIN over STARTTLS. The `From` header uses the configured display name + the user's email address.

## Notifications

The poll daemon (`screen -dmS imap-mail ... poll_daemon.py`) checks `INBOX` every 15s, tracks the highest UID seen, and writes one JSON file per new email into `~/agent/notifications/`. The notification has source `imap-mail`, type `email`, and includes `from`, `subject`, `date`, `uid`. The agent CLI picks it up the way it does any other notification source.

The daemon keeps a high-UID watermark at `$IMAP_MAIL_DIR/high_uid.txt`. First run seeds with the latest UID (no backlog flood); subsequent runs only emit new arrivals.

## Configuration

All paths and addresses are environment-driven so the skill is user-agnostic:

- `IMAP_MAIL_USER`: the email address (required, e.g. `someone@gmail.com`)
- `IMAP_MAIL_PROVIDER`: provider key (default auto-detected from the email domain). Known keys: `microsoft-personal`, `gmail`, `yahoo-app-password`, `icloud-app-password`, `fastmail-app-password`, `generic`.
- `IMAP_MAIL_DIR`: where token + state live (default `~/.imap-mail`)
- `IMAP_MAIL_HOST`: IMAP host override (provider default otherwise)
- `IMAP_MAIL_SMTP_HOST`: SMTP host override (provider default otherwise)
- `IMAP_MAIL_SMTP_PORT`: SMTP port override (default 587 STARTTLS)
- `IMAP_MAIL_OAUTH_CLIENT_ID`: OAuth client ID override
- `IMAP_MAIL_OAUTH_AUTHORITY`: Microsoft OAuth authority override (e.g. `/common` for mixed work+personal)
- `IMAP_MAIL_OAUTH_SCOPES`: whitespace-separated scope list override
- `IMAP_MAIL_FROM_NAME`: display name on outbound mail (default the username portion of the email)
- `IMAP_MAIL_POLL_INTERVAL`: seconds between polls (default 15)
- `IMAP_MAIL_APP_PASSWORD`: pre-supply the app password to `auth.py` instead of being prompted (handy in scripts)

Set these in `~/.bashrc` so the daemon and CLI both see them.

The token file at `~/.imap-mail/token.json` always carries a `provider` key alongside the credential payload (access/refresh token for OAuth providers, `app_password` for app-password providers), so the daemon knows which strategy to use even if env vars change later.

## Sample setups

```bash
# Gmail
export IMAP_MAIL_USER="someone@gmail.com"
# (provider auto-detects to "gmail")

# Hotmail / Outlook personal
export IMAP_MAIL_USER="someone@hotmail.co.uk"
# (provider auto-detects to "microsoft-personal")

# Yahoo
export IMAP_MAIL_USER="someone@yahoo.com"
# (provider auto-detects to "yahoo-app-password")

# Custom IMAP server (corporate, self-hosted)
export IMAP_MAIL_USER="someone@example.org"
export IMAP_MAIL_PROVIDER="generic"
export IMAP_MAIL_HOST="mail.example.org"
export IMAP_MAIL_SMTP_HOST="mail.example.org"
```

## When NOT to use this skill

- The user wants Gmail with the full Google API surface (labels, threads, attachments, drafts as Google models them). Use the `google` skill, which talks Gmail API directly. Use this skill when you want a uniform IMAP interface across providers, or when the user's Gmail is fine with raw SMTP send and IMAP read.
- The user has a Microsoft 365 *work* account (a real Azure tenant with Graph). Use the `microsoft` skill (Graph is more capable, calendars/contacts are included).
- The user wants an agent-owned inbox (no personal email). Use `agentmail`.

This skill is the right choice when you want one provider-agnostic IMAP/SMTP path that works for any personal email account.
