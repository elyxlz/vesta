Hello world. First wake. Do these in order, then stop:

1. Read `/run/vestad-env` for ports, token, timezone, `AGENT_SEED_PERSONALITY` (already exported as env vars).
2. Run `~/agent/skills/upstream-sync/SETUP.md` end to end (git init, branch, checkpoint).
3. In MEMORY.md, replace every `[agent_name]` with your name.
4. Run `~/agent/core/skills/personality/SETUP.md` end to end (registers the voice in the restart skill, adopts it now).
5. Set up tasks, app-chat, and dashboard from their SKILL.md / SETUP.md. Silently, no asking.
