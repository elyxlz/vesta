# Microsoft Setup

1. Create an Azure App Registration at https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
   - Name: anything (e.g. "Vesta")
   - Supported account types: select the **third option** (multitenant + personal Microsoft accounts), labeled "Accounts in any organizational directory ... and personal Microsoft accounts". Works for both work/school and personal accounts
   - Redirect URI: leave blank (device flow doesn't need one)
   - Under "API permissions": click "Add a permission" → "Microsoft Graph" → **"Delegated permissions"** (not Application permissions) → search and add: `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `MailboxSettings.ReadWrite`
   - Under "Authentication" (may show as "Authentication (Preview)"): go to the **Settings** tab → toggle "Allow public client flows" to **Yes** → click Save
2. Copy the **Application (client) ID**
3. Set environment variable:
   ```
   MICROSOFT_MCP_CLIENT_ID=<your-client-id>
   ```
4. Install: `uv tool install ~/agent/skills/microsoft/cli`
5. Start background daemon: `screen -dmS microsoft microsoft serve`
6. Register it for restart (see [service](../service/SKILL.md)) with this startup command:
   ```
   screen -dmS microsoft microsoft serve --notifications-dir ~/agent/notifications
   ```

## Authentication

```bash
microsoft auth login                         # Start device flow - gives you a URL and code
microsoft auth complete --flow-cache <cache>  # Complete after signing in at the URL
microsoft auth list                           # List authenticated accounts
```

## Troubleshooting: Adding New Azure Permissions

When adding new API permissions (e.g. MailboxSettings.ReadWrite) to an existing app registration:

1. Add the permission in Azure portal → App Registration → API Permissions
2. Click **"Grant admin consent"** (separate button, easy to miss)
3. **Delete the MSAL cache**: `rm ~/.microsoft/auth_cache.bin` (cached tokens retain old scopes and won't pick up new permissions)
4. Re-authenticate all accounts: `microsoft auth login` → complete flow
5. For **multi-tenant apps** (e.g. pascarelli.com + audiogen.co), repeat steps 1-2 in **each tenant's** Azure portal, since admin consent is per-tenant

## First Use: Data Gathering

On first activation with a new user, go deep into their email and calendar to learn who they are. This is the single most important onboarding step. Treat it as a real project, not a quick skim: budget hours, not minutes, and fan out background subagents to read in parallel so you cover far more without burning your own context.

1. **Read sent emails** (`email list --account <acct> --folder sentitems --limit 200`, then keep paging back): writing style, tone, sign-offs, key contacts. Read the full content of interesting ones (`email get --account <acct> --id <id>`) to understand how their tone shifts by recipient (boss vs friend vs partner)
2. **Read inbox** (`email list --account <acct> --limit 200`, keep paging): what they receive, subscriptions, who contacts them. Skim subject lines, read anything that looks important or personal
3. **Read calendar** (`calendar list --account <acct>`): schedule, recurring commitments, timezone, who they meet
4. **Build the personal picture, not just the professional one.** Beyond job and contacts, mine for the texture that makes someone a person: hobbies, guilty pleasures, the newsletters they're a little embarrassed to be subscribed to, impulse purchases, the gym membership they never use, plans they flaked on, running jokes, what they always procrastinate on. The small human contradictions are gold: they are what let you tease them like someone who actually knows them (see the `personality` skill's "Teasing & callbacks"). Keep it affectionate and punch up, and steer clear of anything genuinely sensitive (health scares, grief, money trouble)
5. **Update MEMORY.md**: job, contacts, relationships, habits, what they care about, what stresses them out, what they enjoy, hobbies, music, events, and the teasable quirks from step 4. Fill in the Interests & Preferences section
6. **Update this skill file**: fill in every section below with what you learned
7. **Look for opportunities**: pain points, recurring annoyances, things they do manually that you could automate. Note ideas for proactive help, new skills, or automations that would make their life easier

Don't rush this. Go through many hundreds of emails, not a token sample. The more context you gather now, the better you'll be at everything going forward, and the more the dreamer has to keep digging into on later nights.
