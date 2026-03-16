# Microsoft Setup

1. Create an Azure App Registration at https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
   - Name: anything (e.g. "Vesta")
   - Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
   - Redirect URI: leave blank (device flow doesn't need one)
   - Under "API permissions", add: `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`
   - Under "Authentication", enable "Allow public client flows"
2. Copy the **Application (client) ID**
3. Set environment variable:
   ```
   MICROSOFT_MCP_CLIENT_ID=<your-client-id>
   ```
4. Install: `uv tool install {install_root}/tools/microsoft`
5. Start background daemon: `screen -dmS microsoft microsoft serve`

## Authentication

```bash
microsoft auth login                         # Start device flow — gives you a URL and code
microsoft auth complete --flow-cache <cache>  # Complete after signing in at the URL
microsoft auth list                           # List authenticated accounts
```

## First Use — Data Gathering

On first activation with a new user, spend significant time analyzing their email and calendar data to learn their patterns. This is critical for being immediately useful:

1. **Read sent emails** (`email list --account <acct> --folder sentitems --limit 50`) — reveals writing style, tone, sign-offs, key contacts
2. **Read inbox** (`email list --account <acct> --limit 50`) — shows what they receive, subscriptions, who contacts them
3. **Read calendar** (`calendar list --account <acct>`) — schedule, recurring commitments, timezone
4. **Get full content** of important sent emails (`email get --account <acct> --id <id>`) — understand tone variations by recipient
5. **Update this skill file** — fill in every section below with what you learned
6. **Update MEMORY.md** — add any life details discovered (job, interests, contacts, location, relationships, etc.)

Be thorough. Read dozens of emails. The more context you gather now, the better you can draft emails in their voice, manage their calendar, and anticipate needs.
