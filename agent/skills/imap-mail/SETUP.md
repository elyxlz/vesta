# IMAP Mail Setup

One-time setup. Takes about 2 minutes. Picks the right auth flow for the user's mail provider automatically.

## 1. Set the email address

Tell the agent the user's email and add it to `~/.bashrc`:

```bash
echo 'export IMAP_MAIL_USER="<their-email>"' >> ~/.bashrc
source ~/.bashrc
```

The provider is auto-detected from the email domain. Override with `IMAP_MAIL_PROVIDER` if needed:

```bash
# Force a specific provider profile
export IMAP_MAIL_PROVIDER="gmail"
```

Known provider keys: `microsoft-personal`, `gmail`, `yahoo-app-password`, `icloud-app-password`, `fastmail-app-password`, `generic`.

For the `generic` profile (custom IMAP server), also set `IMAP_MAIL_HOST` and `IMAP_MAIL_SMTP_HOST` (and `IMAP_MAIL_SMTP_PORT` if not 587).

## 2. Install the CLI

```bash
mkdir -p ~/.imap-mail/runtime
cd ~/.imap-mail/runtime
uv init --bare --python 3.11
uv add msal aiohttp
ln -sf ~/agent/skills/imap-mail/imap_client.py ~/.imap-mail/imap_client.py
ln -sf ~/agent/skills/imap-mail/smtp_send.py ~/.imap-mail/smtp_send.py
ln -sf ~/agent/skills/imap-mail/poll_daemon.py ~/.imap-mail/poll_daemon.py
ln -sf ~/agent/skills/imap-mail/providers.py ~/.imap-mail/providers.py
ln -sf ~/agent/skills/imap-mail/auth.py ~/.imap-mail/auth.py
sudo cp ~/agent/skills/imap-mail/bin/imap-mail /usr/local/bin/imap-mail 2>/dev/null || cp ~/agent/skills/imap-mail/bin/imap-mail /usr/local/bin/imap-mail
sudo cp ~/agent/skills/imap-mail/bin/imap-mail-send /usr/local/bin/imap-mail-send 2>/dev/null || cp ~/agent/skills/imap-mail/bin/imap-mail-send /usr/local/bin/imap-mail-send
chmod +x /usr/local/bin/imap-mail /usr/local/bin/imap-mail-send
```

`msal` is only needed for Microsoft providers. The Gmail loopback flow and app-password providers use only stdlib.

## 3. Authenticate

The agent runs:

```bash
cd ~/.imap-mail/runtime
uv run python3 ~/agent/skills/imap-mail/auth.py
```

What happens next depends on the auto-detected provider.

### Microsoft personal (device flow)

The CLI prints something like:

```
Visit:  https://www.microsoft.com/link
Code:   ABCD1234
```

The user opens the URL on any device, types the code, and signs in with their email. The script polls for completion and writes the token to `~/.imap-mail/token.json` (mode 600). Refresh token lifetime is ~90 days; the CLI auto-refreshes the access token transparently.

The consent screen will say "Mozilla Thunderbird" because that's the public client ID being reused. That's expected.

### Gmail (loopback OAuth)

The CLI prints a Google consent URL and listens on `http://127.0.0.1:<random-port>/`. The user opens the URL in any browser that can reach this host (same machine, same LAN, or via SSH tunnel: `ssh -L <port>:127.0.0.1:<port> <host>`), signs in, and approves. The CLI captures the authorization code, exchanges it for tokens, and writes them to `~/.imap-mail/token.json`.

The consent screen will say "Mozilla Thunderbird" for the same reason as above.

If the user is on a headless box and can't reach the loopback port from their browser, set up an SSH port forward first, or run the auth on a workstation and copy `~/.imap-mail/token.json` over.

### Yahoo / iCloud / Fastmail / generic (app password)

The CLI prompts for an app password. The user generates one in their provider's account settings:

- Yahoo: Account Info -> Account security -> Generate app password
- iCloud: appleid.apple.com -> Sign-In and Security -> App-Specific Passwords
- Fastmail: Settings -> Privacy & Security -> App passwords (scope: IMAP/SMTP)

Paste it into the prompt. The password is written to `~/.imap-mail/token.json` (mode 600). The CLI uses it as basic-auth for both IMAP and SMTP.

To skip the interactive prompt (e.g. in scripts), pre-export `IMAP_MAIL_APP_PASSWORD` before running `auth.py`.

### Forcing a specific provider

```bash
uv run python3 ~/agent/skills/imap-mail/auth.py --provider gmail
uv run python3 ~/agent/skills/imap-mail/auth.py --provider generic
uv run python3 ~/agent/skills/imap-mail/auth.py --reauth   # replace existing token
```

## 4. Smoke test

```bash
imap-mail list --folder INBOX --limit 3
imap-mail-send --to "<user-email>" --subject "imap-mail test" --body "self-send to verify smtp"
```

If both work, you're good.

## 5. Start the poll daemon

```bash
screen -dmS imap-mail bash -c "cd ~/.imap-mail/runtime && PYTHONUNBUFFERED=1 uv run python3 ~/.imap-mail/poll_daemon.py --interval 15 > ~/.imap-mail/poll_daemon.log 2>&1"
```

Add to `~/agent/prompts/restart.md` so it comes back after every container restart.

## Troubleshooting

- `LOGIN failed.` on first IMAP command, no OAuth: you're not using XOAUTH2 against a Microsoft account that requires it. Personal Microsoft accounts have basic-auth disabled; the device flow above is mandatory for them.
- `acquire_token_by_refresh_token` returns an error after some weeks: the Microsoft refresh token expired. Re-run `auth.py --reauth`.
- Gmail `invalid_grant` on refresh: the user revoked access in their Google account, or the refresh token aged out (rare for installed apps but possible). Re-run `auth.py --provider gmail --reauth`.
- Yahoo / iCloud `LOGIN failed`: app password rotated or wrong. Generate a new one and `auth.py --reauth`.
- Loopback OAuth `bind: Address already in use`: another process held the port between probe and bind. Re-run; the CLI picks a fresh random port each time.
- Notifications don't appear: confirm `~/agent/notifications/` is the right path for your agent (it's the standard one) and the daemon is in `screen -ls`.
- Mailbox has a million emails and `imap-mail list --limit 200` is slow: that's expected, IMAP `SEARCH ALL` then `FETCH` is O(n). Use `search --query 'SINCE <date>'` to scope.
