The `google` skill no longer signs in through Thunderbird's shared public OAuth
client, and its calendar commands moved from CalDAV to the official Google
Calendar REST API. New sign-ins require the user's **own** Google Cloud OAuth
client (Desktop app type) at `~/.google/credentials.json`. An existing token
minted under the shared client keeps refreshing, so **Gmail keeps working for
now**, but **calendar is broken**: the Calendar REST API is disabled on the
shared client's Cloud project, so every calendar command 403s until the user
either completes the bring-your-own-client setup and signs in again, or moves to
the `email-client` skill. For everyday Gmail mail and calendar `email-client` is
the right home: zero-setup sign-in, no Google Cloud project. Safe to run more
than once: every step checks before acting and no-ops when already converged.

### 1. Check whether this applies to you

If `~/agent/skills/google` does not exist, the google skill is not installed on
this box; skip to the final step.

If `~/.google/credentials.json` already exists, you already run your own OAuth
client and nothing changes for you (calendar simply switched backend; note that
event ids are now Calendar API event ids, so any stored iCalendar UIDs no longer
resolve); skip to the final step.

### 2. Talk to the user and pick a path

Otherwise your google sign-in ran on the shared Thunderbird client. Tell the
user, in your own words: Gmail through the google skill keeps working for now
(the old token still refreshes), but its calendar commands are broken because
the Calendar REST API is disabled on the shared client's Cloud project, there is
no longer any self-heal if that shared client dies, and new sign-ins require
their own Google Cloud OAuth client. For ordinary Gmail mail and calendar the
`email-client` skill does the same job with zero-setup sign-in
(`email-client auth add`). Recommend email-client unless they genuinely need
Google-native APIs. Offer the two paths and follow their choice:

- **Move to email-client (recommended).** Install the `email-client` skill if it
  is missing, add their Gmail account with `email-client auth add`, then remove
  the google skill:

  ```bash
  ~/agent/skills/skills-registry/scripts/skills-remove google
  ```

  If it prints that `google` is not installed, there is nothing to remove. Also
  drop the `google serve` daemon line from your restart daemons (the `## Daemons`
  section of `~/agent/skills/restart/SKILL.md`) and quit any running session
  (`screen -S google -X quit`), so a dead daemon does not keep erroring.

- **Keep the google skill (they need Google-native APIs).** Walk them through
  creating a Desktop app OAuth client per `~/agent/skills/google/SETUP.md`
  (create a Google Cloud project, enable the Gmail and Calendar APIs, download
  the client JSON to `~/.google/credentials.json`), then sign in again with
  `google auth login`: the old token stays tied to the shared client, so calendar
  only starts working once a fresh token is minted under their own client.

If the user does not respond right now, leave it with them and continue; the
google CLI's own errors point at SETUP.md, and this migration is still marked
applied below (do not let it re-run every boot waiting on the user).

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-google-skill-byo-client"`.
