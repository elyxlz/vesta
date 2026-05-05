---
name: email-client
description: Personal email via IMAP/SMTP for any provider (Gmail, Outlook/Hotmail/Microsoft personal, Yahoo, iCloud, Fastmail, generic IMAP). Multi-account. Read inbox, send mail, get notified on new mail. OAuth2 where supported, app-password fallback otherwise. Requires daemon.
---

# Email Client

Provider-agnostic IMAP and SMTP for the user's personal email accounts. Supports any number of accounts side by side. Each account gets its own credential, watermark, and notification stream.

Supported providers:

- **Microsoft personal** (`outlook.com`, `hotmail.com`, `live.com`) via OAuth2 device flow + Mozilla Thunderbird's public client ID
- **Gmail** via OAuth2 loopback flow + Thunderbird's public Google client ID
- **Yahoo Mail** via app password
- **iCloud Mail** via app password
- **Fastmail** via app password
- **Generic IMAP/SMTP** (any host, any auth) via per-account config

The provider is auto-detected from each account's email domain. Override per account via `--provider` on `email-client auth add`, or with `EMAIL_CLIENT_PROVIDER` in the environment.

The skill ships three commands:

- `email-client list-folders / list / get / search` for read access
- `email-client-send` for outbound mail
- A poll daemon that watches every registered account's `INBOX` and writes a notification JSON to `~/agent/notifications/` on every new message, so the agent gets paged in real time

The daemon shares the same per-account token cache and refreshes OAuth access tokens transparently. Once the user has run `email-client auth add` once per account, no re-auth is needed for the lifetime of the refresh token (Microsoft ~90 days, Google effectively until revoked) or until the app password is rotated.

**Setup**: see [SETUP.md](SETUP.md). It covers all auth strategies and walks each one end to end. Setup is one-time per account, takes about 2 minutes.

## Why XOAUTH2 + Thunderbird's client IDs

Microsoft killed basic-auth IMAP for personal accounts in late 2024, and tenantless Azure app registrations were deprecated mid-2025. So the only OAuth2 path for a personal Microsoft account that doesn't require the user to register an Azure tenant is to reuse a published public OAuth client ID. Thunderbird's Microsoft client ID is `9e5f94bc-e8a4-4e73-b8be-63364c29d753`, baked into Thunderbird's source, and is the canonical "open-source mail client" choice many tools (mutt-with-xoauth2, getmail, mbsync wrappers, etc) use for the same reason.

Google's situation is similar but with one twist: Google deprecated OAuth device flow for non-TV/non-input-constrained desktop apps, so the supported equivalent is the loopback redirect flow (`http://127.0.0.1:<port>/`). This skill spins up a tiny `http.server` on a random port, opens (or prints) the consent URL, and captures the authorization code from the redirect. Thunderbird's Google client ID is `406964657835-aq8lmia8j95dhl1a2bvharmfk3t1glqf.apps.googleusercontent.com`.

Both client IDs are public, not secrets.

For Yahoo, iCloud, Fastmail, and generic IMAP, the providers expose either no OAuth or no public client at all, so we fall back to **app passwords**: the user generates a one-off password in their account security settings and we store it (chmod 600). Yahoo/iCloud both warn the user this is normal for "less secure apps".

## Read commands

```bash
email-client list-folders --account personal
email-client list --account personal --folder INBOX --limit 20
email-client list --account work --folder Sent --limit 50
email-client get --account personal --folder INBOX --uid 12345
email-client get --account personal --folder INBOX --uid 12345 --body-chars 8000
email-client search --account work --folder INBOX --query 'FROM "stripe"'
email-client search --account personal --folder INBOX --query 'SUBJECT "wedding"'
email-client search --account personal --folder INBOX --query 'SINCE 1-Jan-2026'
```

Omit `--account` to use the default account from `accounts.json`. `list` and `search` return JSON arrays of `{uid, from, to, subject, date}`. `get` returns the full message including a decoded plain-text body.

## Send

```bash
email-client-send --account personal --to "user@example.com" --subject "Hi" --body "first line\\nsecond line"
```

Sends as the configured user for the chosen account. OAuth providers use SMTP STARTTLS XOAUTH2; app-password providers use plain LOGIN over STARTTLS. The `From` header uses the configured display name + the user's email address.

### Reply threading

To send a proper threaded reply to an existing message, pass `--reply-to-uid <uid>` (and `--reply-folder <folder>` if the original is not in `INBOX`):

```bash
email-client-send --account personal --reply-to-uid 12345 --body "thanks, will do"
```

When `--reply-to-uid` is set, the skill fetches the original message via IMAP from the same account and:

- threads the reply via `In-Reply-To` and `References` headers (preserving the existing chain)
- defaults the subject to `Re: <original subject>` (no double prefix if it already starts with `Re:` / `RE:` / `Re :`)
- defaults `--to` to the original sender's address if you omit it
- appends a quoted version of the original body below an `On <date>, <from> wrote:` separator

Override any of these by passing the corresponding flag explicitly. Suppress the quoted body with `--no-quote`. Use `--dry-run` to print the would-send message without actually contacting SMTP, handy for verifying the headers before firing.

```bash
email-client-send --account personal --reply-to-uid 12345 --body "ack" --no-quote
email-client-send --account work --reply-folder Archive --reply-to-uid 999 --body "looking now" --dry-run
email-client-send --account personal --reply-to-uid 12345 --to "alice@example.com" --body "looping in alice"
```

## Account management

```bash
email-client auth add --account personal              # auto-detect provider from email
email-client auth add --account work --provider gmail # force a provider
email-client auth list                                # JSON array of registered accounts
email-client auth remove --account old
```

The first added account becomes the default. To change the default, edit `$EMAIL_CLIENT_DIR/accounts.json` directly.

## Notifications

The poll daemon (`screen -dmS email-client ... poll_daemon.py`) checks every registered account's `INBOX` every 15s, keeps a per-account high-UID watermark, and writes one JSON file per new email into `~/agent/notifications/`. The notification has source `email-client`, type `email`, an `account` field naming the source mailbox, and includes `from`, `subject`, `date`, `uid`. The agent CLI picks it up the way it does any other notification source.

Filenames look like `email-client-personal-1746480000000-abc123.json` so concurrent notifications across accounts never collide.

The daemon keeps each account's high-UID watermark at `$EMAIL_CLIENT_DIR/accounts/<name>/high_uid.txt`. First run for an account seeds with the latest UID (no backlog flood); subsequent runs only emit new arrivals.

## State layout

```
$EMAIL_CLIENT_DIR/                # default ~/.email-client
  accounts.json                   # {"accounts": ["personal","work"], "default": "personal"}
  accounts/
    personal/
      config.json                 # {"user": "...", "provider": "...", optional host overrides}
      token.json                  # OAuth token or {"app_password": "..."} (mode 600)
      high_uid.txt                # daemon poll watermark
    work/
      config.json
      token.json
      high_uid.txt
```

## Configuration

Most settings live per account in `accounts/<name>/config.json`. Environment variables provide defaults that apply to whichever account is being used:

- `EMAIL_CLIENT_DIR`: where token + state live (default `~/.email-client`)
- `EMAIL_CLIENT_USER`: default email address (used at `auth add` time when `--user` is omitted)
- `EMAIL_CLIENT_PROVIDER`: default provider key
- `EMAIL_CLIENT_HOST`: IMAP host override
- `EMAIL_CLIENT_SMTP_HOST`: SMTP host override
- `EMAIL_CLIENT_SMTP_PORT`: SMTP port override (default 587 STARTTLS)
- `EMAIL_CLIENT_OAUTH_CLIENT_ID`: OAuth client ID override
- `EMAIL_CLIENT_OAUTH_AUTHORITY`: Microsoft OAuth authority override (e.g. `/common` for mixed work+personal)
- `EMAIL_CLIENT_OAUTH_SCOPES`: whitespace-separated scope list override
- `EMAIL_CLIENT_FROM_NAME`: display name on outbound mail (default the username portion of the email)
- `EMAIL_CLIENT_POLL_INTERVAL`: seconds between polls (default 15)
- `EMAIL_CLIENT_APP_PASSWORD`: pre-supply the app password to the auth flow instead of being prompted (handy in scripts)

The token file at `accounts/<name>/token.json` always carries a `provider` key alongside the credential payload (access/refresh token for OAuth providers, `app_password` for app-password providers), so the daemon knows which strategy to use even if env vars change later.

## Sample setups

```bash
# Single account (Gmail)
export EMAIL_CLIENT_USER="someone@gmail.com"
email-client auth add --account personal

# Two accounts: personal Gmail + work Outlook
email-client auth add --account personal --user someone@gmail.com
email-client auth add --account work --user someone@outlook.com

# Custom IMAP server (corporate, self-hosted) as a third account
email-client auth add --account selfhosted \
  --user me@example.org --provider generic
# then edit ~/.email-client/accounts/selfhosted/config.json to add
# {"imap_host": "mail.example.org", "smtp_host": "mail.example.org"}
```

## When NOT to use this skill

- The user wants Gmail with the full Google API surface (labels, threads, attachments, drafts as Google models them). Use the `google` skill, which talks Gmail API directly. Use this skill when you want a uniform IMAP interface across providers, or when the user's Gmail is fine with raw SMTP send and IMAP read.
- The user has a Microsoft 365 *work* account (a real Azure tenant with Graph). Use the `microsoft` skill (Graph is more capable, calendars/contacts are included).
- The user wants an agent-owned inbox (no personal email). Use `agentmail`.

This skill is the right choice when you want one provider-agnostic IMAP/SMTP path that works for one or many personal email accounts in parallel.
