The `account` skill was renamed to `vesta-cloud-account`. Only the skill identity
changed (its directory and the `name:` in its `SKILL.md`). The CLI command is still
`vesta-cloud-account`, and the referral code it stores (`~/.config/vesta/referral_code`,
shared with `onboard`) is untouched, so nothing you set up needs redoing.

`vesta-cloud-account` is a default skill, so if it is missing your box installs it
automatically on boot (the default-skill sync turn). This migration only clears the
old `account` entry from your installed set so it does not linger. Safe to run more
than once: it no-ops if you never had `account` installed.

### 1. Drop the old `account` skill

```bash
~/agent/skills/skills-registry/scripts/skills-remove account
```

If it prints that `account` is not installed, you never had it and there is nothing
to do. If it errors because the old directory holds uncommitted local changes, commit
them (`git -C ~ add agent/skills && git -C ~ commit -m "checkpoint skill edits"`) and
run it again.

### 2. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-rename-account-skill"`.
