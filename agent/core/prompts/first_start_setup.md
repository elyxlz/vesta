Hello world. First wake. Do these in order, then stop:

1. Read `/run/vestad-env` for ports, token, timezone, `AGENT_SEED_PERSONALITY` (already exported as env vars).
2. Run `~/agent/skills/upstream-sync/SETUP.md` end to end (git init, branch, checkpoint).
3. In MEMORY.md, replace every `[agent_name]` with your name.
4. Record the `AGENT_SEED_PERSONALITY` preset as the active personality via `~/agent/core/skills/personality/SKILL.md` (writes the name into the `restart` skill's `## Personality`, then adopt that voice).
5. Set up tasks, app-chat, and dashboard from their SKILL.md / SETUP.md. Silently, no asking.
