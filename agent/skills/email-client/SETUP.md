# Email Client Setup

One-time setup per account. Takes about 2 minutes. Picks the right auth flow for the user's mail provider automatically.

## 1. Install the CLI

```bash
mkdir -p ~/.email-client/runtime
cd ~/.email-client/runtime
uv init --bare --python 3.11
uv add msal aiohttp
ln -sf ~/agent/skills/email-client/imap_client.py ~/.email-client/imap_client.py
ln -sf ~/agent/skills/email-client/smtp_send.py ~/.email-client/smtp_send.py
ln -sf ~/agent/skills/email-client/poll_daemon.py ~/.email-client/poll_daemon.py
ln -sf ~/agent/skills/email-client/providers.py ~/.email-client/providers.py
ln -sf ~/agent/skills/email-client/auth.py ~/.email-client/auth.py
sudo cp ~/agent/skills/email-client/bin/email-client /usr/local/bin/email-client 2>/dev/null || cp ~/agent/skills/email-client/bin/email-client /usr/local/bin/email-client
sudo cp ~/agent/skills/email-client/bin/email-client-send /usr/local/bin/email-client-send 2>/dev/null || cp ~/agent/skills/email-client/bin/email-client-send /usr/local/bin/email-client-send
chmod +x /usr/local/bin/email-client /usr/local/bin/email-client-send
```

`msal` is only needed for Microsoft providers. The Gmail loopback flow and app-password providers use only stdlib.

## 2. Add the first account

```bash
email-client auth add --account personal --user someone@gmail.com
```

What happens next depends on the auto-detected provider. The first account you add becomes the default; later commands without `--account` will use it.

You can also force a provider:

```bash
email-client auth add --account work --user me@example.org --provider generic
email-client auth add --account personal --user someone@gmail.com --provider gmail
```

To replace an existing token without removing the account:

```bash
email-client auth add --account personal --reauth
```

To add a second account:

```bash
email-client auth add --account work --user someone@outlook.com
```

To inspect or remove accounts:

```bash
email-client auth list
email-client auth remove --account old
```

### Microsoft personal (device flow)

The CLI prints something like:

```
Visit:  https://www.microsoft.com/link
Code:   ABCD1234
```

The user opens the URL on any device, types the code, and signs in with the right email. The script polls for completion and writes the token to `~/.email-client/accounts/<name>/token.json` (mode 600). Refresh token lifetime is ~90 days; the CLI auto-refreshes the access token transparently.

The consent screen will say "Mozilla Thunderbird" because that's the public client ID being reused. That's expected.

### Gmail (loopback OAuth)

The CLI prints a Google consent URL and listens on `http://127.0.0.1:<random-port>/`. The user opens the URL in any browser that can reach this host (same machine, same LAN, or via SSH tunnel: `ssh -L <port>:127.0.0.1:<port> <host>`), signs in, and approves. The CLI captures the authorization code, exchanges it for tokens, and writes them to `~/.email-client/accounts/<name>/token.json`.

The consent screen will say "Mozilla Thunderbird" for the same reason as above.

If the user is on a headless box and can't reach the loopback port from their browser, set up an SSH port forward first, or run the auth on a workstation and copy the token file over.

### Yahoo / iCloud / Fastmail / generic (app password)

The CLI prompts for an app password. The user generates one in their provider's account settings:

- Yahoo: Account Info -> Account security -> Generate app password
- iCloud: appleid.apple.com -> Sign-In and Security -> App-Specific Passwords
- Fastmail: Settings -> Privacy & Security -> App passwords (scope: IMAP/SMTP)

Paste it into the prompt. The password is written to `~/.email-client/accounts/<name>/token.json` (mode 600). The CLI uses it as basic-auth for both IMAP and SMTP.

To skip the interactive prompt (e.g. in scripts), pre-export `EMAIL_CLIENT_APP_PASSWORD` before running `auth add`.

## 3. Smoke test

```bash
email-client list --account personal --folder INBOX --limit 3
email-client-send --account personal --to "<user-email>" --subject "email-client test" --body "self-send to verify smtp"
email-client-send --account personal --to "<user-email>" --subject "with attachment" --body "see file" --attach /etc/hostname
email-client attachments --account personal --uid <uid-of-the-attached-send>
```

To verify reply threading without actually firing a message, use `--dry-run` against a real UID from the smoke-test send above:

```bash
email-client-send --account personal --reply-to-uid <uid-of-self-send> --body "test reply" --dry-run
email-client-send --account personal --reply-to-uid <uid> --cc someone@example.com --body "with cc" --dry-run
email-client-send --account personal --forward-uid <uid> --to someone@example.com --body "fwd" --dry-run
```

To smoke test mailbox edits:

```bash
email-client mark --uid <uid> --read
email-client mark --uid <uid> --flagged
email-client archive --uid <uid>
email-client delete --uid <uid>          # soft, recoverable from Deleted
email-client delete --uid <uid> --hard   # permanent
```

If both work, you're good. Repeat for every additional account.

## 4. Start the poll daemon

```bash
screen -dmS email-client bash -c "cd ~/.email-client/runtime && PYTHONUNBUFFERED=1 uv run python3 ~/.email-client/poll_daemon.py --interval 15 > ~/.email-client/poll_daemon.log 2>&1"
```

The daemon reads `~/.email-client/accounts.json` each tick, so adding new accounts via `email-client auth add` does not require a daemon restart. Add the `screen` line to `~/agent/prompts/restart.md` so it comes back after every container restart.

## Troubleshooting

- `LOGIN failed.` on first IMAP command, no OAuth: you're not using XOAUTH2 against a Microsoft account that requires it. Personal Microsoft accounts have basic-auth disabled; the device flow above is mandatory for them.
- `acquire_token_by_refresh_token` returns an error after some weeks: the Microsoft refresh token expired. Re-run `email-client auth add --account <name> --reauth`.
- Gmail `invalid_grant` on refresh: the user revoked access in their Google account, or the refresh token aged out (rare for installed apps but possible). Re-run `email-client auth add --account <name> --provider gmail --reauth`.
- Yahoo / iCloud `LOGIN failed`: app password rotated or wrong. Generate a new one and `email-client auth add --account <name> --reauth`.
- Loopback OAuth `bind: Address already in use`: another process held the port between probe and bind. Re-run; the CLI picks a fresh random port each time.
- Notifications don't appear: confirm `~/agent/notifications/` is the right path for your agent (it's the standard one) and the daemon is in `screen -ls`.
- Mailbox has a million emails and `email-client list --limit 200` is slow: that's expected, IMAP `SEARCH ALL` then `FETCH` is O(n). Use `search --query 'SINCE <date>'` to scope.
- `unknown account 'foo'`: run `email-client auth list` to see what's registered. Add the missing one with `email-client auth add --account foo`.
- Microsoft 365 with a custom domain (e.g. `you@yourcompany.com`): see SKILL.md "Microsoft 365 with a custom domain". The short version: use `--provider generic` with `EMAIL_CLIENT_OAUTH_AUTHORITY=https://login.microsoftonline.com/common` and the same `outlook.office365.com` / `smtp.office365.com` hosts. If device flow returns `AADSTS50020` or "needs admin consent", the org disabled third-party OAuth clients; admin must register an internal Azure app and you set `EMAIL_CLIENT_OAUTH_CLIENT_ID` to that one. If OAuth succeeds but `LOGIN failed` follows, the org disabled IMAP/SMTP on the mailbox; either get them re-enabled (`Set-CASMailbox -ImapEnabled $true`) or use the `microsoft` skill (Graph API) instead.
