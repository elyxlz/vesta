# Email Client Setup

One-time setup per account, ~2 minutes. Auth flow is picked automatically from the email domain. One run wires the daemon and both binaries to a shared per-account token cache; refresh is transparent.

## Auth strategy per provider

- **Microsoft personal** (`outlook.com`, `hotmail.com`, `live.com`): OAuth2 **device flow**.
- **Microsoft 365 work** (custom domain on Exchange Online): OAuth2 **device flow** via `--provider microsoft-work`.
- **Gmail**: OAuth2 **loopback flow** (`http://127.0.0.1:<port>/`).
- **Yahoo / iCloud / Fastmail / generic IMAP**: **app password**.

Both OAuth flows reuse Thunderbird's published public client IDs: Microsoft `9e5f94bc-e8a4-4e73-b8be-63364c29d753`, Google `406964657835-aq8lmia8j95dhl1a2bvharmfk3t1hgqj.apps.googleusercontent.com` plus its published desktop secret `kSmqreRr0qwBWJgbf5Y-PjSU` (Google's token endpoint requires it; the skill sends it). These are public, not secrets — the only OAuth path that avoids registering an Azure tenant. Google's device flow is deprecated for desktop, so Gmail uses the loopback redirect captured via a throwaway `http.server` on a random port. Providers with no public OAuth client fall back to app passwords (chmod 600). Both consent screens say "Mozilla Thunderbird" — expected. (The retired Google client `...t1glqf` returns `invalid_client`; the live one is `...t1hgqj`.)

**Google Calendar in the same sign-in.** The `...t1hgqj` client sits under Mozilla's verified Google Cloud project (number `406964657835`), whose consent screen grants mail, calendar, and contacts together. So one Gmail consent also grants `https://www.googleapis.com/auth/calendar` and the `calendar` commands (see SKILL.md) work with no own Google app, no verification, no CASA (`auth/calendar` is "sensitive", not "restricted"). Gmail accounts authed before this change must re-auth once to pick up the calendar scope and corrected client id: `email-client auth add --account <name> --provider gmail --reauth`.

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

`imap_tools` wraps the IMAP layer; `msal` is only for Microsoft OAuth refresh (Gmail loopback uses stdlib `urllib`).

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

Open the URL on any device, enter the code, sign in with the right email. The script polls, then writes the token to `~/.email-client/accounts/<name>/token.json` (mode 600). Refresh token lifetime ~90 days; access token auto-refreshes.

### Gmail - loopback OAuth

The CLI prints a Google consent URL and listens on `http://127.0.0.1:<random-port>/`. Open the URL in any browser that can reach this host (same machine, same LAN, or SSH tunnel: `ssh -L <port>:127.0.0.1:<port> <host>`), sign in, approve. The CLI captures the code, exchanges it, writes tokens to `token.json`. On a headless box where the browser can't reach the loopback port, forward the port first or run auth on a workstation and copy the token file over.

### Yahoo / iCloud / Fastmail / generic - app password

The CLI prompts for an app password. Generate one in the provider's security settings:

- Yahoo: Account Info → Account security → Generate app password
- iCloud: appleid.apple.com → Sign-In and Security → App-Specific Passwords
- Fastmail: Settings → Privacy & Security → App passwords (scope: IMAP/SMTP)

Paste at the prompt; it's written to `token.json` (mode 600) and used as basic-auth for IMAP and SMTP. To skip the prompt in scripts, pre-export `EMAIL_CLIENT_APP_PASSWORD`.

## 3. Smoke test

```bash
email-client list --account personal --folder INBOX --limit 3
email-client-send --account personal --to "<user-email>" --subject "email-client test" --body "self-send to verify smtp"
email-client-send --account personal --to "<user-email>" --subject "with attachment" --body "see file" --attach /etc/hostname
email-client attachments --account personal --uid <uid-of-the-attached-send>
```

Verify reply/forward threading with `--dry-run` (prints headers, no SMTP), against a real UID from the self-send:

```bash
email-client-send --account personal --reply-to-uid <uid> --body "test reply" --dry-run
email-client-send --account personal --reply-to-uid <uid> --cc cc1@example.com --body "with cc" --dry-run
email-client-send --account personal --forward-uid <uid> --to recipient@example.com --body "fwd" --dry-run
```

Save a draft (APPENDs to Drafts, no SMTP), then read it back:

```bash
email-client-send --account personal --to "<user-email>" --subject "draft test" --body "review me" --draft
email-client-send --account personal --reply-to-uid <uid> --body "draft reply for review" --draft
email-client list --account personal --folder Drafts --limit 3
```

**Draft-only mode (optional safety):** `EMAIL_DRAFT_ONLY=1` hard-disables sending. Any send/reply/forward is refused before touching SMTP (non-zero exit); `--draft` still works. Truthy: `1`/`true`/`yes` (case-insensitive). Default off. Verify with `EMAIL_DRAFT_ONLY=1 email-client-send --account personal --to "<user-email>" --subject x --body y` (refuses) vs. the same with `--draft` (succeeds).

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

### Calendar (Gmail accounts only)

A Gmail account authed after this change also has Google Calendar in the same token. Smoke-test it:

```bash
email-client calendar list-calendars --account personal
email-client calendar list --account personal --days-ahead 7
email-client calendar create --account personal --subject "email-client cal test" --start 2026-07-20T15:00:00 --end 2026-07-20T15:30:00 --timezone Europe/London
email-client calendar get --account personal --id <eventId-from-create>
email-client calendar delete --account personal --id <eventId-from-create>
```

If `list-calendars` returns `Google Calendar refused the request` or a scope error, the account was authed before calendar support: re-auth once with `email-client auth add --account personal --provider gmail --reauth`. Calendar commands only work on Google accounts; other providers exit with a clear "only supported for Google accounts" message. See SKILL.md "Calendar" for the full command set and the invite-sending caveat.

## 4. Start the poll daemon

```bash
email-client daemon start
```

Idempotent (a running daemon is a no-op); `--interval` defaults to `$EMAIL_CLIENT_POLL_INTERVAL` or 15 seconds. `email-client daemon status` reports process state plus per-account auth health in one JSON blob. `stop` and `restart` are also available; a deliberate stop or restart marks itself intentional first, so it never fires the `daemon_died` notification.

The daemon runs one worker per watched `(account, folder)`. Where the server supports IMAP **IDLE** (Gmail, Microsoft, most others) the worker is pushed on new mail in real time; otherwise it polls every `--interval` seconds (fallback cadence, not the primary mechanism). It recomputes the watch set as accounts or folders change, so no restart is needed when adding an account or changing the watch list.

**Ask the user which folders they want notified about, per account.** No preference → default to **all**. Then set the watch list (see SKILL.md "Choosing which folders notify"):

```bash
email-client notify add --all --account personal     # default: every folder
# or a specific set:
email-client notify add --folder INBOX --account personal
email-client notify add --folder Archive --account personal
```

Without this the daemon watches `INBOX` only. `--all` includes Sent/Drafts/Spam/Trash, which can be noisy; drop any with `email-client notify remove --folder <name>`.

## 5. Register for restart

Add this to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`. The poller only connects out to IMAP and writes notification files, so it needs no inbound port: it is a daemon, not a vestad service.

```
running email-client || { email-client daemon start; sleep 1; }
```

## 6. Wire the rules into MEMORY.md

The skill's "Notes & rules" section (in SKILL.md) is only loaded when you open the skill; it is **not** in your context on every notification. So you reliably apply those rules when email arrives, add a pointer to `~/agent/MEMORY.md` (always in your context). Append it once:

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

A notification looks like this, so your rules can match on `from` / `subject` / `folder`:

```
<channel source="email-client" type="email" account="personal" folder="INBOX" from="Jane Doe &lt;jane@example.com&gt;" subject="Q2 budget review" date="..." uid="12345"></channel>
```

Without this line you still handle email on request, but standing rules (especially "stay silent" / auto-handle rules) may not fire on their own.

## 7. First Use: Data Gathering

Once accounts are connected and the smoke test passes, go deep into the user's mail to learn who they are. This is the single most important onboarding step. Treat it as a real project: budget hours, not minutes, and fan out background subagents to read accounts and folders in parallel so you cover far more without burning your own context.

1. **Map the folders** (`email-client list-folders --account <acct>`): the sent folder may be "Sent", "Sent Items", or "Sent Mail" depending on provider
2. **Read sent mail** (`email-client list --account <acct> --folder Sent --limit 200`, then page back): writing style, tone, sign-offs, key contacts, how tone shifts by recipient. Open interesting ones in full (`email-client get --account <acct> --folder Sent --uid <uid> --body-chars 8000`)
3. **Read inbox** (`email-client list --account <acct> --folder INBOX --limit 200`, keep paging): what they receive, subscriptions, who contacts them. Read anything important or personal. Use `email-client search --account <acct> --folder INBOX --query 'SINCE 1-Jan-2024'` to dig into older threads
4. **Build the personal picture, not just the professional one.** Beyond job and contacts, mine for the texture that makes someone a person: hobbies, guilty pleasures, embarrassing newsletter subscriptions, impulse purchases, the gym membership they never use, plans they flaked on, running jokes, what they always procrastinate on. The small human contradictions are gold: they let you tease them like someone who actually knows them (see the `personality` skill's "Teasing & callbacks"). Keep it affectionate and punch up, and steer clear of anything genuinely sensitive (health scares, grief, money trouble)
5. **Update MEMORY.md**: job, contacts, relationships, habits, what they care about, what stresses them out, what they enjoy, and the teasable quirks from step 4. Fill in the Interests & Preferences section
6. **Look for opportunities**: pain points, recurring annoyances, standing rules worth proposing (see "Notes & rules" in SKILL.md), things you could automate

Repeat for each connected account. Don't rush. Go through many hundreds of emails, not a token sample. The more context you gather now, the better you'll be at everything going forward, and the more the dreamer has to keep digging into on later nights.

## Troubleshooting

- **`LOGIN failed.` on first IMAP command, no OAuth**: not using XOAUTH2 against a Microsoft account that requires it. Personal Microsoft accounts have basic-auth disabled; device flow is mandatory.
- **`acquire_token_by_refresh_token` errors after weeks**: Microsoft refresh token expired. Run `email-client auth add --account <name> --reauth`.
- **Gmail `invalid_grant` on refresh**: access revoked or refresh token aged out. Run `email-client auth add --account <name> --provider gmail --reauth`.
- **Gmail `invalid_client` "The OAuth client was not found"**: token minted against the retired `...t1glqf` client id. Update the skill and re-auth (`email-client auth add --account <name> --provider gmail --reauth`); current client id is `...t1hgqj`.
- **`calendar` command says "only supported for Google accounts"**: calendar is Google-specific; select or add a Gmail account. On a Gmail account, a scope error instead means an old mail-only auth: re-auth with `--reauth`.
- **Yahoo / iCloud `LOGIN failed`**: app password rotated or wrong. Generate a new one and `--reauth`.
- **Loopback OAuth `bind: Address already in use`**: another process grabbed the port between probe and bind. Re-run; the CLI picks a fresh random port each time.
- **Notifications don't appear**: confirm `~/agent/notifications/` is the agent's path (the standard one) and `email-client daemon status` shows `"running": true`. A `daemon_died` notification with a `reason` field means it crashed or was killed outside the CLI; restart with `email-client daemon start`.
- **`list --limit 200` is slow on a huge mailbox**: expected; IMAP `SEARCH ALL` + `FETCH` is O(n). Scope with `search --query 'SINCE <date>'`.
- **`unknown account 'foo'`**: run `email-client auth list`; add the missing one with `email-client auth add --account foo`.
- **Microsoft 365 custom domain** (`you@yourcompany.com`): use `--provider microsoft-work`. See "Microsoft 365 with a custom domain" below for the four org-side blockers (`AADSTS50020` / admin consent, IMAP disabled, SMTP AUTH disabled, Conditional Access).
- **`AADSTS7000012: The grant was obtained for a different tenant`** on refresh ~1h after a working first auth: account authed against `/common` but resolves to a work tenant. Re-auth via `--provider microsoft-work` (or `EMAIL_CLIENT_OAUTH_AUTHORITY=https://login.microsoftonline.com/organizations`) and the refresh sticks.
- **`535 5.7.139 SmtpClientAuthentication is disabled for the Tenant`** on send: tenant blocks SMTP AUTH. IMAP read and `--draft` still work; outbound needs an admin to flip the tenant or per-mailbox switch (see "Microsoft 365 with a custom domain" #3 below).

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
  daemon.pid                      # poll daemon pid; owned by `email-client daemon start|stop|restart|status`
  daemon-info.json                # {"interval", "started_at"} of the running daemon, for `daemon restart`
  stop-requested                  # marker `daemon stop`/`restart` writes so a deliberate exit skips daemon_died
```

`token.json` always carries a `provider` key alongside the credential (access/refresh token for OAuth, `app_password` otherwise), so the daemon knows the auth strategy even if env vars change later.

## Configuration

Settings live per account in `accounts/<name>/config.json`. Env vars provide defaults applied to whichever account is in use:

- `EMAIL_CLIENT_DIR` - token + state location (default `~/.email-client`)
- `EMAIL_CLIENT_USER` - default email address (used at `auth add` when `--user` is omitted)
- `EMAIL_CLIENT_PROVIDER` - default provider key
- `EMAIL_CLIENT_HOST` - IMAP host override
- `EMAIL_CLIENT_SMTP_HOST` / `EMAIL_CLIENT_SMTP_PORT` - SMTP host / port (default 587 STARTTLS)
- `EMAIL_CLIENT_OAUTH_CLIENT_ID` - OAuth client ID override
- `EMAIL_CLIENT_OAUTH_AUTHORITY` - Microsoft authority override (e.g. `/common` for mixed work+personal)
- `EMAIL_CLIENT_OAUTH_SCOPES` - whitespace-separated scope override
- `EMAIL_CLIENT_FROM_NAME` - display name on outbound mail (default: username portion of the email)
- `EMAIL_CLIENT_POLL_INTERVAL` - seconds between polls (default 15)
- `EMAIL_CLIENT_APP_PASSWORD` - pre-supply the app password to `auth add` instead of prompting (for scripts)

## Microsoft 365 with a custom domain

For an address on a custom domain hosted by M365 (e.g. `you@yourcompany.com`, mailbox on Exchange Online), use the `microsoft-work` provider:

```bash
email-client auth add --account work --provider microsoft-work --user you@yourcompany.com
```

This profile ships the right `outlook.office365.com` IMAP/SMTP hosts, the `Sent Items` folder name M365 work mailboxes use, the Thunderbird multi-tenant OAuth client ID, and `https://login.microsoftonline.com/organizations` as the authority. The authority matters: `/common` mints a usable token the first time but fails refresh ~1 hour later with `AADSTS7000012: The grant was obtained for a different tenant` (it accepts any account type, so refresh can't resolve the tenant). `/organizations` binds the grant to the AAD tenant up front, so refresh works.

Approve the device-flow code at https://www.microsoft.com/link. Four org-side blockers can stop this (none fixable from the skill):

1. **Third-party OAuth clients disabled** → device flow returns `AADSTS50020` / "needs admin consent". Fix: admin registers an internal Azure app with `Mail.ReadWrite` + `SMTP.Send` delegated permissions; set `EMAIL_CLIENT_OAUTH_CLIENT_ID` to it (the env override applies on top of any provider).
2. **IMAP disabled on the mailbox** → `LOGIN`/`AUTHENTICATE` fails after a successful OAuth. Fix: admin runs `Set-CASMailbox -ImapEnabled $true`, or switch to the `microsoft` (Graph) skill.
3. **SMTP AUTH disabled on the tenant** → outbound returns `535 5.7.139 SmtpClientAuthentication is disabled for the Tenant` (the M365 default). Reading and drafts still work over IMAP; outbound is blocked until an admin runs `Set-TransportConfig -SmtpClientAuthenticationDisabled $false` (tenant-wide) or `Set-CASMailbox -Identity user@... -SmtpClientAuthenticationDisabled $false` (per-mailbox). If you can't change it, use `--draft` and let the user send from their normal client, or switch outbound to the `microsoft` (Graph) skill.
4. **Conditional Access policies** → device flow lands on "your sign-in was blocked". Fix: admin must whitelist the app or relax the policy. No client-side workaround.

If 1-4 all check out and it still fails, capture the full error from `email-client auth add --reauth`; the useful detail is usually in the OAuth response's `error_description`.
