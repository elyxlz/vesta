The `account` skill is now a default skill: it lets you answer the owner's
questions about their Vesta hosting plan and facilitate billing changes (upgrade,
cancel, change card) via a secure link. Fresh vestas ship with it, but existing
boxes need it installed once. This migration installs it if missing. Safe to run
more than once: it checks first and no-ops if you already have it.

### 1. Install the account skill if missing

If `~/agent/skills/account/SKILL.md` does not exist, install it:

```bash
~/agent/skills/skills-registry/scripts/skills-install account
```

If it already exists, do nothing.

### 2. Mark this migration applied

Call `mark_migration_applied` with `name="2026-06-account-default-skill"`.
