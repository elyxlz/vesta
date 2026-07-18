The `app-chat` skill moved out of `~/agent/core/skills/` (replaced on every `vestad update`) into `~/agent/skills/` (a normal, installed skill you can personalize like your other channels). Its CLI now lives at `~/agent/skills/app-chat/cli`, so the editable tool install must be re-pointed there. Safe to run more than once: each step checks whether you are already in the end state and no-ops if so.

### 1. Install the app-chat skill at the new location

If `~/agent/skills/app-chat/SKILL.md` does not exist, install it:

```bash
~/agent/skills/skills-registry/scripts/skills-install app-chat
```

### 2. Re-point the `app-chat` CLI at its new source

Your `app-chat` tool may still be an editable install pointing at the old `~/agent/core/skills/app-chat/cli`, which is gone after this update. Reinstall it from the new source so `app-chat send` keeps working:

```bash
uv tool install --editable --force --reinstall ~/agent/skills/app-chat/cli
```

This is transactional: a failed rebuild leaves the existing tool exactly as it was.

### 3. Restart the daemon so it runs the live code

```bash
app-chat daemon restart
```

### 4. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-app-chat-out-of-core"`.
