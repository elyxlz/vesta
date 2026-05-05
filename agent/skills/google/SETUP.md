# Google Setup

1. Go to https://console.cloud.google.com/ and create a project (or use an existing one)
2. Enable the **Gmail API**, **Google Calendar API**, and **Google Meet REST API** under "APIs & Services" > "Library"
3. Go to "APIs & Services" > "Credentials" > "Create Credentials" > "OAuth client ID"
   - Application type: **Desktop app**
   - Download the JSON file
4. Place the credentials file at `~/.google/credentials.json`
5. Install: `uv tool install ~/agent/skills/google/cli`
6. Start background daemon: `screen -dmS google google serve`
7. Add to the `## Services` section of `~/agent/skills/restart/SKILL.md`:
   ```
   screen -dmS google google serve --notifications-dir ~/agent/notifications
   ```

## Authentication

```bash
google auth login                   # Start OAuth flow - gives you a URL to visit
google auth complete --code <code>  # Complete after authorizing and pasting the code from redirect URL
google auth login-local             # Alternative: runs local server to handle redirect automatically
google auth list                    # Show authenticated account
```

## First Use: Data Gathering

On first activation with a new user, go deep into their email and calendar to learn who they are. This is the single most important onboarding step.

1. **Read sent emails** (`email list --label SENT --limit 200`): writing style, tone, sign-offs, key contacts. Read the full content of interesting ones (`email get --id <id>`) to understand tone variations by recipient
2. **Read inbox** (`email list --limit 200`): what they receive, subscriptions, who contacts them. Skim subject lines, read anything that looks important or personal
3. **Read calendar** (`calendar list`): schedule, recurring commitments, timezone
4. **Update MEMORY.md**: add everything you learn: job, contacts, relationships, habits, what they care about, what stresses them out, what they enjoy, hobbies, music, events. Fill in the Interests & Preferences section
5. **Update this skill file**: fill in every section below with what you learned
6. **Look for opportunities**: pain points, recurring annoyances, things they do manually that you could automate. Note ideas for proactive help, new skills, or automations that would make their life easier

Don't rush this. Go through hundreds of emails. The more context you gather now, the better you'll be at everything going forward.
