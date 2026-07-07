The `service` skill is now a default skill: it holds the `register-service`
helper that registers a background daemon with vestad to get a port, plus the
convention for keeping it alive across restarts. Other skills (dashboard, tasks,
voice, webhook receivers) reference it during setup. Fresh vestas ship with it,
but existing boxes need it installed once. This migration installs it if missing.
Safe to run more than once: it checks first and no-ops if you already have it.

### 1. Install the service skill if missing

If `~/agent/skills/service/SKILL.md` does not exist, install it:

```bash
~/agent/skills/skills-registry/scripts/skills-install service
```

If it already exists, do nothing.

### 2. Mark this migration applied

Call `mark_migration_applied` with `name="2026-06-service-default-skill"`.
