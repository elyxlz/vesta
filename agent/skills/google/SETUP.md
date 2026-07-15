# Google Setup

**Bring your own Google Cloud OAuth client.** This skill talks to the official
Google REST APIs (Gmail + Calendar v3) and requires the user's own OAuth client
JSON at `~/.google/credentials.json`. There is no shared sign-in client. If the
user just wants everyday Gmail mail and calendar, install the `email-client`
skill instead: it signs into Gmail with zero setup (no Google Cloud project) and
covers mail plus calendar. Use this skill only when Google-native APIs are
genuinely needed (raised quotas, API surfaces email-client does not cover,
future Meet/conferenceData work).

## 1. Create the OAuth client (one-time, user does this in a browser)

In https://console.cloud.google.com/ with the user's Google account:

1. Create a project (or pick an existing one)
2. Enable the **Gmail API** and the **Google Calendar API**
   (APIs & Services -> Library)
3. Configure the OAuth consent screen (External is fine; while the app is in
   Testing mode, add the user's own address as a test user)
4. Create credentials -> OAuth client ID -> Application type **Desktop app**
5. Download the client JSON and place it at `~/.google/credentials.json`

## 2. Install and start the daemon

1. Install: `uv tool install --editable ~/agent/skills/google/cli`
2. Start background daemon: `screen -dmS google google serve`
3. Register it for restart (see [vestad](../vestad/SKILL.md)) with this startup command:
   ```
   screen -dmS google google serve --notifications-dir ~/agent/notifications
   ```

## 3. Authentication

Sign-in is a **loopback OAuth** flow: it prints a consent URL and runs a
`127.0.0.1:<port>` listener for the redirect. It does **not** auto-open a browser
on this host, the sign-in happens in a separately-driven handover browser.

```bash
google auth login                   # Start OAuth flow, prints a consent URL to visit
google auth complete --code <code>  # Complete after authorizing and pasting the code from redirect URL
google auth login-local             # Alternative: runs the local loopback server to capture the redirect automatically
google auth list                    # Show authenticated account
```

Requested scopes: `https://mail.google.com/` (full Gmail) and
`https://www.googleapis.com/auth/calendar`; one consent screen grants both.

The sign-in commands (`auth login`, `auth login-local`, `auth complete`) require
`~/.google/credentials.json` and fail with a clear error when it is missing;
`auth list` only reads the stored token. A stored token stays tied to the OAuth client that
minted it (its client id/secret ride along in the token file), so a token from a
different client, including the shared Thunderbird client this skill used to
ride, keeps refreshing and Gmail keeps working. Calendar does not: the REST API
403s with `accessNotConfigured` when that client's Cloud project has the
Calendar API disabled (the shared client's project does, permanently). Re-run
`google auth login` after placing your own `credentials.json` to mint a token
under your client and unlock calendar.

### Google Meet

Not implemented here: no `meet` command, and `calendar create` does not attach
`conferenceData`. With your own project nothing blocks it in principle (enable
the Calendar API and any Meet scopes you need); it simply is not wired up.

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
