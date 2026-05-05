# IMAP Mail Setup

One-time setup. Takes about 2 minutes and gets you a long-lived OAuth2 refresh token for the user's personal email.

## 1. Set the email address

Tell the agent the user's email and add it to `~/.bashrc`:

```bash
echo 'export IMAP_MAIL_USER="<their-email>@hotmail.co.uk"' >> ~/.bashrc
source ~/.bashrc
```

For non-Microsoft providers, also set `IMAP_MAIL_HOST`, `IMAP_MAIL_SMTP_HOST`, `IMAP_MAIL_OAUTH_CLIENT_ID`, `IMAP_MAIL_OAUTH_AUTHORITY` per your provider's docs. The defaults target Microsoft personal accounts.

## 2. Install the CLI

```bash
mkdir -p ~/.imap-mail/runtime
cd ~/.imap-mail/runtime
uv init --bare --python 3.11
uv add msal aiohttp
ln -sf ~/agent/skills/imap-mail/imap_client.py ~/.imap-mail/imap_client.py
ln -sf ~/agent/skills/imap-mail/smtp_send.py ~/.imap-mail/smtp_send.py
ln -sf ~/agent/skills/imap-mail/poll_daemon.py ~/.imap-mail/poll_daemon.py
sudo cp ~/agent/skills/imap-mail/bin/imap-mail /usr/local/bin/imap-mail 2>/dev/null || cp ~/agent/skills/imap-mail/bin/imap-mail /usr/local/bin/imap-mail
sudo cp ~/agent/skills/imap-mail/bin/imap-mail-send /usr/local/bin/imap-mail-send 2>/dev/null || cp ~/agent/skills/imap-mail/bin/imap-mail-send /usr/local/bin/imap-mail-send
chmod +x /usr/local/bin/imap-mail /usr/local/bin/imap-mail-send
```

## 3. Run the device flow

This is the only step the user has to do interactively. The agent runs:

```bash
cd ~/.imap-mail/runtime
uv run python3 ~/agent/skills/imap-mail/auth.py
```

It prints something like:

```
Visit https://www.microsoft.com/link
Code: ABCD1234
```

The user opens the URL, types the code, and signs in with their email. The script polls for completion and writes the token to `~/.imap-mail/token.json` (mode 600). Token includes a refresh token (~90 day lifetime, auto-refreshed by every CLI call).

For Microsoft personal accounts the consent screen will say "Mozilla Thunderbird" because that's the public client ID being reused. That's expected.

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

- `LOGIN failed.` on first IMAP command, no OAuth: you're not using XOAUTH2. Personal Microsoft accounts have basic-auth disabled; the device flow above is mandatory.
- `acquire_token_by_refresh_token` returns an error after some weeks: the refresh token expired. Re-run step 3.
- `bind: Address already in use` from the daemon's HTTP server: the daemon doesn't bind a port, only outbound IMAP/SMTP. If you see this, something else is wrong.
- Notifications don't appear: confirm `~/agent/notifications/` is the right path for your agent (it's the standard one) and the daemon is in `screen -ls`.
- Mailbox has a million emails and `imap-mail list --limit 200` is slow: that's expected, IMAP `SEARCH ALL` then `FETCH` is O(n). Use `search --query 'SINCE <date>'` to scope.
