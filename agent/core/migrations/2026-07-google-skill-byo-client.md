The `google` skill no longer signs in through Thunderbird's shared public OAuth
client, and its calendar commands moved from CalDAV to the official Google
Calendar REST API. It now requires the user's **own** Google Cloud OAuth client
(Desktop app type) at `~/.google/credentials.json`; without that file every
`google` command fails, and a token minted under the old shared client cannot
refresh even after the file appears (a fresh `google auth login` is needed).
For everyday Gmail mail and calendar the `email-client` skill is the right home:
zero-setup sign-in, no Google Cloud project. Safe to run more than once: every
step checks before acting and no-ops when already converged.

### 1. Check whether this applies to you

If `~/agent/skills/google` does not exist, the google skill is not installed on
this box; skip to the final step.

If `~/.google/credentials.json` already exists, you already run your own OAuth
client and nothing changes for you (calendar simply switched backend; note that
event ids are now Calendar API event ids, so any stored iCalendar UIDs no longer
resolve); skip to the final step.

### 2. Talk to the user and pick a path

Otherwise your google sign-in ran on the removed shared client and will stop
working. Tell the user, in your own words: the google skill now requires their
own Google Cloud OAuth client, and for ordinary Gmail mail and calendar the
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
  the client JSON to `~/.google/credentials.json`), then re-authenticate with
  `google auth login`; the old token cannot refresh under their new client.

If the user does not respond right now, leave it with them and continue; the
google CLI's own errors point at SETUP.md, and this migration is still marked
applied below (do not let it re-run every boot waiting on the user).

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-google-skill-byo-client"`.
