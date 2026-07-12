# Google Setup

**Zero bring-your-own-app.** The default sign-in reuses **Mozilla Thunderbird's
published public OAuth client**, so there is **no Google Cloud project to create**
and **no `credentials.json` to download**. Just install, start the daemon, and
sign in.

**What works under this client:** Gmail (via the Gmail REST API) and Google
Calendar (via **CalDAV** — the same path Thunderbird uses). The Calendar *REST*
API and Google Meet are **disabled** for this client's Cloud project and cannot be
used; calendar therefore runs entirely over CalDAV, which needs only the
`.../auth/calendar` scope granted at sign-in.

1. Install: `uv tool install --editable ~/agent/skills/google/cli`
2. Start background daemon: `screen -dmS google google serve`
3. Register it for restart (see [service](../service/SKILL.md)) with this startup command:
   ```
   screen -dmS google google serve --notifications-dir ~/agent/notifications
   ```

## Authentication

Sign-in is a **loopback OAuth** flow: it prints a consent URL and runs a
`127.0.0.1:<port>` listener for the redirect. It does **not** auto-open a browser
on this host — the sign-in happens in a separately-driven handover browser.

```bash
google auth login                   # Start OAuth flow - prints a consent URL to visit
google auth complete --code <code>  # Complete after authorizing and pasting the code from redirect URL
google auth login-local             # Alternative: runs the local loopback server to capture the redirect automatically
google auth list                    # Show authenticated account
google auth probe                   # Check the OAuth client's health + attempt a silent self-heal
```

Requested scopes: `https://mail.google.com/` (full Gmail) and
`https://www.googleapis.com/auth/calendar` (used by CalDAV) — one verified
Thunderbird consent screen grants both.

### Advanced: bring your own Google Cloud app (optional)

If you prefer to run your own OAuth client (e.g. to raise quotas, to use the
Calendar REST API instead of CalDAV, or to enable Meet), create a **Desktop app**
OAuth client in https://console.cloud.google.com/ (enable the Gmail API, and the
Calendar / Meet REST APIs if you want them), download the client JSON, and place
it at `~/.google/credentials.json`. If that file exists it transparently takes
over; its absence is **not** an error. (Note: the calendar backend in this skill
is CalDAV either way — a bring-your-own app is not needed for calendar to work.)

### Google Meet

Meet is unavailable under the default sign-in. Standalone Meet spaces need a
restricted scope the shared client is not verified for, and the calendar
`conferenceData` route needs the Calendar REST API, which is disabled for this
client. There is no `meet` command. A separately-verified own app
(`credentials.json`) with the Meet/Calendar REST APIs enabled would be required to
add it back; that is not wired up here.

### Self-healing sign-in client

The shared Thunderbird client is a commons Google can rotate or delete upstream.
A low-frequency (≤ once/day) daemon probe detects a dead client via a stored-token
refresh and runs an automatic escalation ladder:

- **Level 1 (silent):** re-fetch Thunderbird's current client from comm-central,
  swap it in, re-test. If healthy again → fixed silently (cache + token updated,
  info log only, **no notification**).
- **Level 2 (wake the agent):** if the freshly-fetched client is also dead → write
  an agent-actionable `google_client_heal_request` notification (find/patch a new
  verified client, test, upstream). A marker prevents repeats.
- **Level 3 (user, last resort):** if the heal-request marker already exists from a
  previous cycle and the client is still dead → a plain-English user notification.
  This is the only path that ever reaches the user.

Run `google auth probe` any time to check health and trigger a silent self-heal
attempt manually (it never files an agent/user notification — that is the daemon's
job).

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
