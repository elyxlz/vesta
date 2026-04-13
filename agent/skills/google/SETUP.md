# Google Setup

1. Go to https://console.cloud.google.com/ and create a project (or use an existing one)
2. Enable the **Gmail API**, **Google Calendar API**, and **Google Meet REST API** under "APIs & Services" > "Library"
3. Go to "APIs & Services" > "Credentials" > "Create Credentials" > "OAuth client ID"
   - Application type: **Desktop app**
   - Download the JSON file
4. Place the credentials file at `~/.google/credentials.json`
5. Install: `uv tool install ~/vesta/skills/google/cli`
6. Start background daemon: `screen -dmS google google serve`
7. Add to `~/vesta/prompts/restart.md`:
   ```
   screen -dmS google google serve --notifications-dir ~/vesta/notifications
   ```

## Authentication

```bash
google auth login                   # Start OAuth flow - gives you a URL to visit
google auth complete --code <code>  # Complete after authorizing and pasting the code from redirect URL
google auth login-local             # Alternative: runs local server to handle redirect automatically
google auth list                    # Show authenticated account
```

## First Use - Data Gathering

On first activation with a new user, spend significant time analyzing their email and calendar data to learn their patterns. This is critical for being immediately useful:

1. **Read sent emails** (`email list --label SENT --limit 50`) - reveals writing style, tone, sign-offs, key contacts
2. **Read inbox** (`email list --limit 50`) - shows what they receive, subscriptions, who contacts them
3. **Read calendar** (`calendar list`) - schedule, recurring commitments, timezone
4. **Get full content** of important sent emails (`email get --id <id>`) - understand tone variations by recipient
5. **Update this skill file** - fill in every section below with what you learned
6. **Update MEMORY.md** - add any life details discovered (job, interests, contacts, location, relationships, etc.)

Be thorough. Read dozens of emails. The more context you gather now, the better you can draft emails in their voice, manage their calendar, and anticipate needs.
