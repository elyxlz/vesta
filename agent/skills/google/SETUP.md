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

On first activation with a new user, go deep into their email and calendar to learn who they are. This is the single most important onboarding step. Treat it as a real project, not a quick skim: budget hours, not minutes, and fan out background subagents to read in parallel so you cover far more without burning your own context.

1. **Read sent emails** (`email list --label SENT --limit 200`, then keep paging back): writing style, tone, sign-offs, key contacts. Read the full content of interesting ones (`email get --id <id>`) to understand how their tone shifts by recipient (boss vs friend vs partner)
2. **Read inbox** (`email list --limit 200`, keep paging): what they receive, subscriptions, who contacts them. Skim subject lines, read anything that looks important or personal
3. **Read calendar** (`calendar list`): schedule, recurring commitments, timezone, who they meet
4. **Build the personal picture, not just the professional one.** Beyond job and contacts, mine for the texture that makes someone a person: hobbies, guilty pleasures, the newsletters they're a little embarrassed to be subscribed to, impulse purchases, the gym membership they never use, plans they flaked on, running jokes, what they always procrastinate on. The small human contradictions are gold: they are what let you tease them like someone who actually knows them (see the `personality` skill's "Teasing & callbacks"). Keep it affectionate and punch up, and steer clear of anything genuinely sensitive (health scares, grief, money trouble)
5. **Update MEMORY.md**: job, contacts, relationships, habits, what they care about, what stresses them out, what they enjoy, hobbies, music, events, and the teasable quirks from step 4. Fill in the Interests & Preferences section
6. **Update this skill file**: fill in every section below with what you learned
7. **Look for opportunities**: pain points, recurring annoyances, things they do manually that you could automate. Note ideas for proactive help, new skills, or automations that would make their life easier

Don't rush this. Go through many hundreds of emails, not a token sample. The more context you gather now, the better you'll be at everything going forward, and the more the dreamer has to keep digging into on later nights.
