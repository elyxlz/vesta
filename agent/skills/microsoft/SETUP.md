# Microsoft Setup

1. Create an Azure App Registration at https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
   - Name: anything (e.g. "Vesta")
   - Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
   - Redirect URI: leave blank (device flow doesn't need one)
   - Under "API permissions", add: `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `MailboxSettings.ReadWrite`
   - Under "Authentication", enable "Allow public client flows"
2. Copy the **Application (client) ID**
3. Set environment variable:
   ```
   MICROSOFT_MCP_CLIENT_ID=<your-client-id>
   ```
4. Install: `uv tool install ~/vesta/skills/microsoft/cli`
5. Start background daemon: `screen -dmS microsoft microsoft serve`
6. Add to `~/vesta/prompts/restart.md`:
   ```
   screen -dmS microsoft microsoft serve --notifications-dir ~/vesta/notifications
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

On first activation with a new user, go deep into their email and calendar to learn who they are. This is the single most important onboarding step.

1. **Read sent emails** (`email list --account <acct> --folder sentitems --limit 200`): writing style, tone, sign-offs, key contacts. Read the full content of interesting ones (`email get --account <acct> --id <id>`) to understand tone variations by recipient
2. **Read inbox** (`email list --account <acct> --limit 200`): what they receive, subscriptions, who contacts them. Skim subject lines, read anything that looks important or personal
3. **Read calendar** (`calendar list --account <acct>`): schedule, recurring commitments, timezone
4. **Update MEMORY.md**: add everything you learn: job, contacts, relationships, habits, what they care about, what stresses them out, what they enjoy, hobbies, music, events. Fill in the Interests & Preferences section
5. **Update this skill file**: fill in every section below with what you learned
6. **Look for opportunities**: pain points, recurring annoyances, things they do manually that you could automate. Note ideas for proactive help, new skills, or automations that would make their life easier

Don't rush this. Go through hundreds of emails. The more context you gather now, the better you'll be at everything going forward.
