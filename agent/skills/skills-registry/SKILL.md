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

Some skills have functions the Vesta app (or other network clients) need to call over HTTP (e.g. the `voice` skill exposes `/voice/status`, `/voice/tts/speak`, etc.). Wire them up by appending rows to the `SKILL_ENDPOINTS` table in `~/vesta/src/vesta/api.py`:

1. Look at the skill's Python modules to find the handler functions. Each handler takes an aiohttp `web.Request` and returns a response:
   ```bash
   ls ~/vesta/skills/<name>/
   ```
2. Edit `~/vesta/src/vesta/api.py` — find `SKILL_ENDPOINTS` near the top and append one tuple per endpoint:
   ```python
   SKILL_ENDPOINTS: list[tuple[str, str, str]] = [
       ...,
       ("GET",  "/<name>/foo",  "<name>.handlers:foo"),
       ("POST", "/<name>/bar",  "<name>.handlers:bar"),
   ]
   ```
   Format: `(METHOD, PATH, "module:function")`. The module path is resolved against `~/vesta/skills/` (added to `sys.path` at startup), so `"voice.handlers:status"` means `skills/voice/handlers.py::status`. WebSocket handlers use method `"GET"`.
3. Restart via `restart_vesta`.

**Constraints:**
- The skill's directory name must be a valid Python identifier (no hyphens) if it exposes HTTP functions.
- Handlers read shared state via `request.app["config"]` (a `VestaConfig`). Anything beyond config (paths, settings) should be stored in files under `config.data_dir`.
- A broken import in one row is logged and skipped — it won't prevent the server from starting.

Skills that are LLM-only don't need this step.

## Check what's installed

```bash
ls ~/vesta/skills/
```

## Notes

- Skills you install are downloaded from `agent/skills/<name>/` in the GitHub repo
- Core skills ship pre-installed; optional skills are downloaded on demand
- After installing a skill that requires setup, read its `SETUP.md`
- If the skill has HTTP handlers, also edit `api.py` per above
