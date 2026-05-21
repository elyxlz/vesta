# Email Client Setup

One-time setup per account, ~2 minutes. The right auth flow is picked automatically from the email domain.

## Auth strategy per provider

Run this once and the daemon and both binaries share the same per-account token cache and refresh tokens transparently.

- **Microsoft personal** (`outlook.com`, `hotmail.com`, `live.com`): OAuth2 **device flow**.
- **Microsoft 365 work** (custom domain on Exchange Online): OAuth2 **device flow** via `--provider microsoft-work`.
- **Gmail**: OAuth2 **loopback flow** (`http://127.0.0.1:<port>/`).
- **Yahoo / iCloud / Fastmail / generic IMAP**: **app password**.

Both OAuth flows reuse Mozilla Thunderbird's published public client IDs (Microsoft `9e5f94bc-e8a4-4e73-b8be-63364c29d753`, Google `406964657835-aq8lmia8j95dhl1a2bvharmfk3t1glqf.apps.googleusercontent.com`). These are public, not secrets, and are the canonical open-source-mail-client choice. The reason: Microsoft killed basic-auth IMAP for personal accounts in late 2024 and deprecated tenantless Azure app registrations mid-2025, so reusing a published client ID is the only OAuth path that doesn't require the user to register an Azure tenant. Google deprecated the device flow for desktop apps, so its supported equivalent is the loopback redirect, which the skill captures via a throwaway `http.server` on a random port. Providers with no public OAuth client fall back to app passwords (chmod 600).

This is why both OAuth consent screens say "Mozilla Thunderbird". That is expected, not a misconfiguration.

## 1. Install

```bash
mkdir -p ~/.email-client/runtime
cd ~/.email-client/runtime
uv init --bare --python 3.11
uv add imap_tools msal aiohttp
ln -sf ~/agent/skills/email-client/imap_client.py ~/.email-client/imap_client.py
ln -sf ~/agent/skills/email-client/smtp_send.py ~/.email-client/smtp_send.py
ln -sf ~/agent/skills/email-client/poll_daemon.py ~/.email-client/poll_daemon.py
ln -sf ~/agent/skills/email-client/providers.py ~/.email-client/providers.py
ln -sf ~/agent/skills/email-client/auth.py ~/.email-client/auth.py
sudo cp ~/agent/skills/email-client/bin/email-client /usr/local/bin/email-client 2>/dev/null || cp ~/agent/skills/email-client/bin/email-client /usr/local/bin/email-client
sudo cp ~/agent/skills/email-client/bin/email-client-send /usr/local/bin/email-client-send 2>/dev/null || cp ~/agent/skills/email-client/bin/email-client-send /usr/local/bin/email-client-send
chmod +x /usr/local/bin/email-client /usr/local/bin/email-client-send
```

`imap_tools` wraps the IMAP read/manage layer. `msal` is only for Microsoft OAuth refresh; the Gmail loopback flow uses stdlib `urllib`.

## 2. Add the first account

```bash
email-client auth add --account personal --user you@gmail.com
```

The first account added becomes the default; later commands without `--account` use it. What happens next depends on the auto-detected provider (below). Force a provider or re-auth:

```bash
email-client auth add --account work --user you@example.org --provider generic
email-client auth add --account personal --reauth     # replace token, keep account
email-client auth list                                # inspect
email-client auth remove --account old
```

### Microsoft personal - device flow

The CLI prints a URL and a code:

```
Visit:  https://www.microsoft.com/link
Code:   ABCD1234
```

The user opens the URL on any device, enters the code, and signs in with the right email. The script polls for completion and writes the token to `~/.email-client/accounts/<name>/token.json` (mode 600). Refresh token lifetime ~90 days; the access token auto-refreshes.

### Gmail - loopback OAuth

The CLI prints a Google consent URL and listens on `http://127.0.0.1:<random-port>/`. The user opens the URL in any browser that can reach this host (same machine, same LAN, or via SSH tunnel: `ssh -L <port>:127.0.0.1:<port> <host>`), signs in, and approves. The CLI captures the code, exchanges it, and writes tokens to `token.json`. On a headless box where the browser can't reach the loopback port, forward the port first or run auth on a workstation and copy the token file over.

### Yahoo / iCloud / Fastmail / generic - app password

The CLI prompts for an app password. Generate one in the provider's security settings:

- Yahoo: Account Info → Account security → Generate app password
- iCloud: appleid.apple.com → Sign-In and Security → App-Specific Passwords
- Fastmail: Settings → Privacy & Security → App passwords (scope: IMAP/SMTP)

Paste it at the prompt; it's written to `token.json` (mode 600) and used as basic-auth for IMAP and SMTP. To skip the prompt in scripts, pre-export `EMAIL_CLIENT_APP_PASSWORD`.

## 3. Smoke test

```bash
email-client list --account personal --folder INBOX --limit 3
email-client-send --account personal --to "<user-email>" --subject "email-client test" --body "self-send to verify smtp"
email-client-send --account personal --to "<user-email>" --subject "with attachment" --body "see file" --attach /etc/hostname
email-client attachments --account personal --uid <uid-of-the-attached-send>
```

Verify reply/forward threading with `--dry-run` (prints headers without contacting SMTP), against a real UID from the self-send above:

```bash
email-client-send --account personal --reply-to-uid <uid> --body "test reply" --dry-run
email-client-send --account personal --reply-to-uid <uid> --cc cc1@example.com --body "with cc" --dry-run
email-client-send --account personal --forward-uid <uid> --to recipient@example.com --body "fwd" --dry-run
```

Save a draft (APPENDs to the Drafts folder, no SMTP), then read it back:

```bash
email-client-send --account personal --to "<user-email>" --subject "draft test" --body "review me" --draft
email-client-send --account personal --reply-to-uid <uid> --body "draft reply for review" --draft
email-client list --account personal --folder Drafts --limit 3
```

Verify mailbox edits, folder counts, and folder management:

```bash
email-client status --folder INBOX                  # counts, no fetch
email-client mark --uid <uid> --read
email-client mark --uid <uid> --flagged
email-client mark --uid <uid> --keyword Receipts     # custom keyword / Outlook category
email-client mark --uid <uid> --unkeyword Receipts
email-client folder create --name email-client-test
email-client move --uid <uid> --to-folder email-client-test
email-client folder rename --name email-client-test --to-name email-client-test2
email-client notify add --folder email-client-test2     # daemon now also watches it
email-client notify list
email-client notify remove --folder email-client-test2
email-client folder delete --name email-client-test2
email-client archive --uid <uid>
email-client delete --uid <uid>          # soft, recoverable from Deleted
email-client delete --uid <uid> --hard   # permanent
```

If these work, repeat steps 2-3 for each additional account.

## 4. Start the poll daemon

```bash
screen -dmS email-client bash -c "cd ~/.email-client/runtime && PYTHONUNBUFFERED=1 uv run python3 ~/.email-client/poll_daemon.py --interval 15 > ~/.email-client/poll_daemon.log 2>&1"
```

The daemon runs one worker per watched `(account, folder)`. Where the server supports IMAP **IDLE** (Gmail, Microsoft, most others) the worker is pushed on new mail in real time; otherwise it polls every `--interval` seconds (the flag is the fallback cadence, not the primary mechanism). It recomputes the watch set as accounts or folders change, so neither adding an account nor changing the watch list needs a restart.

**Ask the user which folders they want to be notified about, per account.** If they have no preference, default to **all** folders. Then set the watch list (see SKILL.md "Choosing which folders notify"):

```bash
email-client notify add --all --account personal     # default: every folder
# or a specific set:
email-client notify add --folder INBOX --account personal
email-client notify add --folder Archive --account personal
```

Without this the daemon watches `INBOX` only. Note that `--all` includes folders like Sent/Drafts/Spam/Trash, which can be noisy; drop any the user doesn't want with `email-client notify remove --folder <name>`.

## 5. Add to restart.md

```
screen -dmS email-client bash -c "cd ~/.email-client/runtime && PYTHONUNBUFFERED=1 uv run python3 ~/.email-client/poll_daemon.py --interval 15 > ~/.email-client/poll_daemon.log 2>&1"
```

## 6. Wire the rules into MEMORY.md

The skill's "Notes & rules" section (in SKILL.md) is only loaded when you open the skill; it is **not** in your context on every notification. So that you reliably apply those rules when email arrives, add a pointer to `~/agent/MEMORY.md` (your system prompt, always in your context). Append it once:

```bash
cat >> ~/agent/MEMORY.md <<'EOF'

## Email
You manage the user's email through the email-client skill. Whenever you receive an
`email-client` notification (`source=email-client`), first open the email-client skill
and read its "Notes & rules" section, then apply every rule that matches the
notification - including deciding whether to surface the email to the user at all.
Do this before taking any other action on the email.
EOF
```

A notification arrives to you looking like this, so your rules can match on `from` / `subject` / `folder`:

```
<notification source="email-client" type="email">account=personal, folder=INBOX, from=Jane Doe <jane@example.com>, subject=Q2 budget review, date=..., uid=12345</notification>
```

Without this line you still handle email on request, but standing rules (especially "stay silent" / auto-handle rules) may not fire on their own.

## Troubleshooting

- **`LOGIN failed.` on first IMAP command, no OAuth**: not using XOAUTH2 against a Microsoft account that requires it. Personal Microsoft accounts have basic-auth disabled; the device flow is mandatory.
- **`acquire_token_by_refresh_token` errors after weeks**: Microsoft refresh token expired. Run `email-client auth add --account <name> --reauth`.
- **Gmail `invalid_grant` on refresh**: access revoked or the refresh token aged out. Run `email-client auth add --account <name> --provider gmail --reauth`.
- **Yahoo / iCloud `LOGIN failed`**: app password rotated or wrong. Generate a new one and `--reauth`.
- **Loopback OAuth `bind: Address already in use`**: another process grabbed the port between probe and bind. Re-run; the CLI picks a fresh random port each time.
- **Notifications don't appear**: confirm `~/agent/notifications/` is the agent's path (it's the standard one) and the daemon shows in `screen -ls`.
- **`list --limit 200` is slow on a huge mailbox**: expected; IMAP `SEARCH ALL` + `FETCH` is O(n). Scope with `search --query 'SINCE <date>'`.
- **`unknown account 'foo'`**: run `email-client auth list`; add the missing one with `email-client auth add --account foo`.
- **Microsoft 365 custom domain** (`you@yourcompany.com`): use `--provider microsoft-work`. See SKILL.md "Microsoft 365 with a custom domain" for the four org-side blockers (`AADSTS50020` / admin consent, IMAP disabled, SMTP AUTH disabled, Conditional Access).
- **`AADSTS7000012: The grant was obtained for a different tenant`** on refresh ~1h after a working first auth: account was authed against `/common` but resolves to a work tenant. Re-auth via `--provider microsoft-work` (or `EMAIL_CLIENT_OAUTH_AUTHORITY=https://login.microsoftonline.com/organizations`) and the refresh sticks.
- **`535 5.7.139 SmtpClientAuthentication is disabled for the Tenant`** on send: tenant blocks SMTP AUTH. IMAP read and `--draft` still work; outbound needs an admin to flip the tenant or per-mailbox switch (see SKILL.md M365 troubleshooting #3).
