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

## If the skill needs an HTTP server

Vesta has a built-in reverse proxy (`~/vesta/src/vesta/proxy.py`) that makes any server running inside the container reachable from the outside through the agent's single port — like a minimal nginx.

To expose a server:

1. Edit `~/vesta/src/vesta/proxy.py` — find `PROXIED_SERVERS` near the top and append one tuple:
   ```python
   PROXIED_SERVERS: list[tuple[str, int]] = [
       ...,
       ("<name>", 7970),
   ]
   ```
   This proxies `/{name}/*` to `localhost:{port}/*`, stripping the prefix.
2. Start the server (as a background process or daemon).
3. Restart via `restart_vesta`.

**Constraints:**
- The server must listen on `localhost` only.
- WebSocket connections are proxied bidirectionally.
- If the server is unreachable, clients get a 502.

Skills that are LLM-only don't need this step.

## Check what's installed

```bash
ls ~/vesta/skills/
```

## Notes

- Skills you install are downloaded from `agent/skills/<name>/` in the GitHub repo
- Core skills ship pre-installed; optional skills are downloaded on demand
- After installing a skill that requires setup, read its `SETUP.md`
- If the skill runs an HTTP server, register it in `proxy.py` per above
