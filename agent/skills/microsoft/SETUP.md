# Microsoft Setup

No Azure setup is required. The skill defaults to the **Microsoft Graph Command Line Tools**
public client (Microsoft-published, multitenant, device-code capable) and requests the delegated
Graph scopes it needs (`Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`,
`MailboxSettings.ReadWrite`) via dynamic consent at sign-in. Just install, start the daemon, and
authenticate:

1. Install: `uv tool install --editable ~/agent/skills/microsoft/cli`
2. Start background daemon: `screen -dmS microsoft microsoft serve`
3. Register it for restart (see [service](../service/SKILL.md)) with this startup command:
   ```
   screen -dmS microsoft microsoft serve --notifications-dir ~/agent/notifications
   ```

## Optional: your own Azure app registration

Use your own app only if you need to (e.g. a Conditional Access policy blocks the default client,
or you want to pin a narrower scope set). Create one at
https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade:

- Name: anything (e.g. "Vesta")
- Supported account types: select the **third option** (multitenant + personal Microsoft accounts), labeled "Accounts in any organizational directory ... and personal Microsoft accounts". Works for both work/school and personal accounts
- Redirect URI: leave blank (device flow doesn't need one)
- Under "API permissions": click "Add a permission" → "Microsoft Graph" → **"Delegated permissions"** (not Application permissions) → search and add: `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `MailboxSettings.ReadWrite`
- Under "Authentication" (may show as "Authentication (Preview)"): go to the **Settings** tab → toggle "Allow public client flows" to **Yes** → click Save

Then copy the **Application (client) ID** and set `MICROSOFT_MCP_CLIENT_ID=<your-client-id>`
(a custom client uses `.default`, i.e. exactly the permissions you configured above).

## Authentication

**Run one command: `microsoft auth setup --account <email>`.** It provisions mail, calendar, and
Teams together and picks the right path on its own; each step returns a `next:` command telling you
exactly what to run.

```bash
microsoft auth setup --account you@example.com          # start (default depends on domain, see below)
microsoft auth setup --account you@example.com --flow-cache <cache>   # finish a device-code sign-in
microsoft auth setup --account you@example.com --browser             # force browser sign-in (locked tenant)
microsoft auth setup --account you@example.com --device              # force device code (permissive work tenant)
microsoft auth setup --account you@example.com --capture             # finish after the browser sign-in
```

How it chooses (by the account's domain, no need to ask):
- **Personal Microsoft account** (outlook.com, hotmail.*, live.*, msn.com, etc.): defaults to **device-code** sign-in. The user visits a URL and enters a code, once. Tokens auto-refresh via MSAL indefinitely.
- **Work/school account** (any custom domain, e.g. a university or company like UCL): defaults to the **browser handover** up front, because the tenant almost always blocks the default public client and would reject a device code. `auth setup` hands the user **one URL** to sign into their own webmail (SSO + MFA), then captures the token. No admin consent needed. No wasted device-code round-trip.
- **Escape hatches**: `--browser` forces the browser route for any account; `--device` forces device code even for a work/school domain (for a permissive tenant that still allows it). If a device-code sign-in is later walled by the tenant, `auth setup --flow-cache` still **automatically pivots** to the browser handover.

**Auto-refresh (locked tenants):** the user signs in **once**. The browser sign-in is saved to a per-account profile, and the daemon silently re-mints fresh tokens from it before they expire (works for weeks, until the SSO session itself ends), so there's no daily re-login. If the session finally lapses, the daemon emits a `type=auth_needed` notification to sign in again.

```bash
microsoft auth list                           # List device-flow (Graph) accounts
microsoft auth remove --account <email>       # Sign a device-flow account out
```

The commands below (`auth login`/`complete`, `owa-login`, `teams-login`/`teams-capture`) are the
lower-level pieces `auth setup` orchestrates; reach for them only for manual control.

```bash
microsoft auth login                         # Start device flow: gives you a URL and code
microsoft auth complete --flow-cache <cache>  # Complete after signing in at the URL
```

## Fallback backend: OWA REST (locked tenants only)

If the tenant blocks Graph entirely (third-party apps disabled, missing scopes),
use the OWA REST fallback. Locked tenants usually block device-code flow as well,
so the default is a **browser capture**, driven by the agent on its own machine
(the `browser` skill daemon with `DISPLAY=:99`). The agent opens Outlook on the web,
signs in (relaying the user's credentials and MFA through chat), then captures the
`outlook.office.com` token from the live session:

```bash
microsoft auth owa-login --account you@company.com     # captures the token, or returns sign_in_required
microsoft email list --account you@company.com --backend owa-rest
```

If the browser is not signed in yet, `owa-login` returns `sign_in_required` (it does
not block); finish the sign-in with the `browser` skill and run it again. The token
lasts about 24 h; re-run to refresh. With a token in place, `--backend auto` (the
default) falls back to OWA REST automatically whenever Graph returns a permission
error. Every command works on both backends **except** `block`/`unblock` (inbox
rules), which are Graph-only.

**Draft-only mode (optional safety):** set `EMAIL_DRAFT_ONLY=1` in the environment to
hard-disable sending on this CLI. `email send`/`reply`/`forward` are then refused before
any Graph or OWA-REST call (non-zero exit); only `email draft` works. Truthy values:
`1`/`true`/`yes` (case-insensitive). Default off. This guards **both** backends, so it
holds for an OWA-REST-only FAO/work account too.

When the agent cannot reach the user's browser (agent on another machine), let the user sign in on
their **own** browser and paste just the token, so their password and MFA never reach the agent. Give
them the one-line snippet `auth_commands.OWA_TOKEN_SNIPPET` to run in the Outlook DevTools console (it
copies the token to their clipboard), then:

```bash
microsoft auth owa-login --account you@company.com --token <PASTED_TOKEN>
```

**Tenants that still permit device flow:** `microsoft auth owa-login --account you@company.com --device`
does a device-code sign-in instead (enter a code at a URL, no browser), finished with
`microsoft auth owa-complete --account you@company.com --flow-cache <cache>`. MSAL then
auto-refreshes that token.

## Microsoft Teams

Teams uses the same client and daemon as mail, but has its **own** sign-in so a mail-only account is
never prompted for Teams scopes. The Teams scopes (`Chat.ReadWrite`, `ChannelMessage.Send`,
`Team.ReadBasic.All`, `Channel.ReadBasic.All`, `Presence.ReadWrite`) are all user-consentable, so no
admin approval is needed for chats, channel posting, or presence:

```bash
microsoft auth teams-login                           # device flow: gives a URL and code
microsoft auth teams-complete --flow-cache <cache>   # complete after signing in
microsoft teams chats --account you@company.com
```

Locked tenant (blocks the CLI's app registration)? Capture a token from Teams on the web, the same
mechanism as `owa-login`:

```bash
microsoft auth teams-capture --account you@company.com     # browser capture, or sign_in_required
microsoft teams chats --account you@company.com --backend owa-rest
```

**Reading channel messages** (`microsoft teams channel-messages`) is the one Teams operation that
needs the admin-only `ChannelMessage.Read.All` scope. Add it to your own app registration (below) and
have a tenant admin grant consent; everything else (chats, channel posting, presence) works without
it. For an own app registration, add these **Delegated** Graph permissions alongside the mail ones:
`Chat.ReadWrite`, `ChannelMessage.Send`, `ChannelMessage.Read.All`, `Team.ReadBasic.All`,
`Channel.ReadBasic.All`, `Presence.ReadWrite`.

## Troubleshooting: Adding New Azure Permissions

When adding new API permissions (e.g. MailboxSettings.ReadWrite) to an existing app registration:

1. Add the permission in Azure portal → App Registration → API Permissions
2. Click **"Grant admin consent"** (separate button, easy to miss)
3. **Delete the MSAL cache**: `rm ~/.microsoft/auth_cache.bin` (cached tokens retain old scopes and won't pick up new permissions)
4. Re-authenticate all accounts: `microsoft auth login` → complete flow
5. For **multi-tenant apps** (e.g. pascarelli.com + audiogen.co), repeat steps 1-2 in **each tenant's** Azure portal, since admin consent is per-tenant

## First Use: Data Gathering

The moment an account finishes connecting, DO this, don't wait to be asked. Go deep into their email and calendar to learn who they are. This is the single most important onboarding step, and it is proactive: reading what you just connected is the whole point of connecting it, so start immediately rather than gating on a fresh permission. For a work/school or otherwise sensitive account, a one-line heads-up that you're doing the gathering is courteous, but it is a heads-up, not a request for permission: the reading still happens. Treat it as a real project, not a quick skim: budget hours, not minutes, and fan out background subagents to read in parallel so you cover far more without burning your own context.

1. **Read sent emails** (`email list --account <acct> --folder sentitems --limit 200`, then keep paging back): this is the single richest source, so mine their **communication patterns** as a default, not an afterthought. Capture: writing voice per language and register (formal vs casual), exact greetings and sign-offs (how they open, how they close, what they sign), how tone and formality shift by recipient (boss vs peer vs friend vs family), sending cadence and timing (when in the day, how fast they reply), typical length, and recurring phrases or quirks. The goal is to be able to draft in their exact voice so a draft reads like them, not like an assistant. Read the full content of representative ones (`email get --account <acct> --id <id>`) across different recipients to see the shifts.
2. **Read inbox** (`email list --account <acct> --limit 200`, keep paging): what they receive, subscriptions, who contacts them. Skim subject lines, read anything that looks important or personal
3. **Read calendar** (`calendar list --account <acct>`): schedule, recurring commitments, timezone, who they meet
4. **Build the personal picture, not just the professional one.** Beyond job and contacts, mine for the texture that makes someone a person: hobbies, guilty pleasures, the newsletters they're a little embarrassed to be subscribed to, impulse purchases, the gym membership they never use, plans they flaked on, running jokes, what they always procrastinate on. The small human contradictions are gold: they are what let you tease them like someone who actually knows them (see the `personality` skill's "Teasing & callbacks"). Keep it affectionate and punch up, and steer clear of anything genuinely sensitive (health scares, grief, money trouble)
5. **Update MEMORY.md**: job, contacts, relationships, habits, what they care about, what stresses them out, what they enjoy, hobbies, music, events, and the teasable quirks from step 4. Fill in the Interests & Preferences section
6. **Update this skill file**: fill in every section below with what you learned
7. **Look for opportunities**: pain points, recurring annoyances, things they do manually that you could automate. Note ideas for proactive help, new skills, or automations that would make their life easier

Don't rush this. Go through many hundreds of emails, not a token sample. The more context you gather now, the better you'll be at everything going forward, and the more the dreamer has to keep digging into on later nights.
