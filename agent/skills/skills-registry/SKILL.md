---
name: skills-registry
description: Discover and install new capabilities from the skill registry. Use this when asked to add a new feature, when you want to explore what you could do, or when a user asks if you can do something you don't have a skill for yet. The registry lives on GitHub — search it to find skills, then install them to give yourself new abilities.
---

# Skills Manager

Vesta's skills come from a registry on GitHub (`agent/skills/`). You can search for new skills and install them on demand. Installed skills are activated on the next restart.

## Search the registry

```bash
~/vesta/skills/skills-registry/scripts/skills-search                  # list all available skills
~/vesta/skills/skills-registry/scripts/skills-search email            # search by keyword
```

## Install a skill

```bash
~/vesta/skills/skills-registry/scripts/skills-install <name>
```

After installing, restart yourself with the `restart_vesta` tool to load the new skill into context.

## If the skill exposes HTTP functions

Some skills run their own HTTP server that the agent reverse-proxies (e.g. the `voice` skill serves on a local port and requests to `/voice/*` are forwarded to it). Wire them up by appending a row to `SKILL_SERVERS` in `~/vesta/src/vesta/skill_server.py`:

1. Check if the skill runs an HTTP server and what port it listens on:
   ```bash
   ls ~/vesta/skills/<name>/
   ```
2. Edit `~/vesta/src/vesta/skill_server.py` — find `SKILL_SERVERS` near the top and append one tuple:
   ```python
   SKILL_SERVERS: list[tuple[str, int]] = [
       ...,
       ("<name>", 7970),
   ]
   ```
   Format: `(SKILL_NAME, PORT)`. The proxy strips the `/{skill_name}` prefix and forwards to `localhost:{port}`.
3. Start the skill's HTTP server (as a background process or daemon).
4. Restart via `restart_vesta`.

**Constraints:**
- The skill server must listen on `localhost` only.
- The proxy strips the `/{skill_name}` prefix — the skill server sees paths without it.
- WebSocket connections are proxied bidirectionally.
- If the skill server is unreachable, clients get a 502 error.

Skills that are LLM-only don't need this step.

## Check what's installed

```bash
ls ~/vesta/skills/
```

## Notes

- Skills you install are downloaded from `agent/skills/<name>/` in the GitHub repo
- Core skills ship pre-installed; optional skills are downloaded on demand
- After installing a skill that requires setup, read its `SETUP.md`
- If the skill runs an HTTP server, register it in `skill_server.py` per above
