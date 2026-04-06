---
name: skill-maker
description: Use this skill when asked to create a new skill, add a new capability, build an integration, or when you need to give yourself a new ability that doesn't exist yet. This teaches you the anatomy of a skill, how to give it network access, and how to expose it over HTTP.
---

# Skill Maker

Use this when you need to create a new skill from scratch. A skill is a self-contained directory under `~/vesta/skills/<name>/` that gives you a new capability.

## Skill anatomy

Every skill is a directory with at minimum a `SKILL.md`:

```
~/vesta/skills/<name>/
  SKILL.md              # Required — frontmatter + docs (this is your instruction manual)
  scripts/              # Optional — executable scripts you call
  SETUP.md              # Optional — setup instructions for the user
```

### SKILL.md format

```markdown
---
name: <skill-name>
description: <when should the agent use this skill — be specific about trigger words and scenarios>
---

# <Skill Name>

<What this skill does, how to use it, examples>
```

The `description` field is critical — it's how you (the agent) know when to reach for this skill. Be specific about trigger conditions.

### Scripts

Scripts are standalone executables. They take arguments, do work, print output. You call them from bash.

```bash
# Python script (no install needed)
uv run ~/vesta/skills/<name>/scripts/<script>.py [args]

# Shell script
~/vesta/skills/<name>/scripts/<script>.sh [args]
```

Rules:
- Scripts must be self-contained. Never share code between skill directories.
- Print structured output (JSON preferred) to stdout.
- Print errors to stderr.
- Use exit codes: 0 = success, non-zero = failure.

## Giving a skill network access

Skills that call external APIs need HTTP. Use one of these patterns, simplest first:

### Pattern 1: urllib (built-in, no dependencies)

Best for simple GET/POST with JSON. No install step.

```python
#!/usr/bin/env python3
import json, sys, urllib.request

def fetch(url, headers=None, data=None):
    req = urllib.request.Request(url, headers=headers or {})
    if data:
        req.data = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

# Usage
result = fetch("https://api.example.com/data", headers={"Authorization": f"Bearer {token}"})
print(json.dumps(result))
```

### Pattern 2: httpx (modern, async-capable)

Best when you need session reuse, retries, or streaming. Requires `uv run --with httpx`.

```python
#!/usr/bin/env python3
"""/// script
dependencies = ["httpx"]
///"""
import httpx, json, sys

with httpx.Client(base_url="https://api.example.com", timeout=15.0) as client:
    resp = client.get("/data", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    print(json.dumps(resp.json()))
```

### Authentication

Store credentials in files or environment variables, never hardcoded:

```python
import os
from pathlib import Path

# Environment variable (set in /etc/environment inside the container)
api_key = os.environ["MY_API_KEY"]

# Token file (written during setup)
token = Path.home().joinpath(".config/<name>/token").read_text().strip()
```

If the skill needs OAuth or interactive auth, document the flow in `SETUP.md` and tell the user to run it.

## Exposing a skill over HTTP

If the Vesta app (or other network clients) needs to call skill functions directly — not through the agent — the skill runs its own HTTP server and the agent reverse-proxies it.

### How it works

The agent's main server proxies `/{skill_name}/*` to `localhost:{port}/*`, stripping the skill prefix. For example, if skill `voice` is registered on port 7965, a request to `/voice/stt/status` is forwarded to `localhost:7965/stt/status`. WebSocket upgrades are proxied too.

### Step 1: Build an HTTP server in your skill

Use any framework (aiohttp, FastAPI, plain http.server — whatever fits). The server listens on `localhost:{port}` and handles its own routes.

```python
#!/usr/bin/env python3
"""/// script
dependencies = ["aiohttp"]
///"""
from aiohttp import web

async def status(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})

async def do_thing(request: web.Request) -> web.Response:
    data = await request.json()
    # ... do work ...
    return web.json_response({"result": "done"})

app = web.Application()
app.router.add_get("/status", status)
app.router.add_post("/do-thing", do_thing)

if __name__ == "__main__":
    web.run_app(app, host="localhost", port=7970)
```

### Step 2: Register the skill server

Edit `~/vesta/src/vesta/skill_server.py` and append one tuple to `SKILL_SERVERS`:

```python
SKILL_SERVERS: list[tuple[str, int]] = [
    ...,
    ("<name>", 7970),
]
```

Format: `(SKILL_NAME, PORT)`. Pick an unused port.

### Step 3: Start the server and restart

The skill server must be running before requests can be proxied. Start it as a background process (or as part of a daemon — see the Daemons section). Then restart:

```bash
restart_vesta
```

After restart, requests to `/<name>/*` on the agent's main server are forwarded to your skill's server.

### Constraints

- The skill server must listen on `localhost` only.
- The proxy strips the `/{skill_name}` prefix — your server sees paths without it.
- WebSocket connections are proxied bidirectionally.
- If the skill server is unreachable, clients get a 502 error.

## Daemons (advanced)

Some skills run a persistent background process that monitors an external service and emits notifications. These are for integrations that need real-time event monitoring (e.g. Telegram messages, calendar reminders).

### Structure

```
~/vesta/skills/<name>/
  SKILL.md
  cli/
    pyproject.toml    # Python package with entry point
    src/<name>_cli/
      __init__.py
      cli.py          # argparse entry point with `serve` subcommand
      ...
```

### Install & run

```bash
uv tool install ~/vesta/skills/<name>/cli
<name> serve --notifications-dir ~/vesta/notifications &
```

### Notifications

Daemons emit JSON files to `~/vesta/notifications/` for the agent to pick up:

```json
{
  "timestamp": "2025-04-05T22:00:00",
  "source": "<name>",
  "type": "<event-type>",
  "message": "Something happened",
  "interrupt": true
}
```

Filename: `{microsecond_timestamp}-{source}-{type}.json`

Only build a daemon if the skill needs to monitor events in real time. Most skills are just scripts.

## Checklist

When creating a new skill:

1. Create `~/vesta/skills/<name>/SKILL.md` with frontmatter and docs
2. Add scripts to `~/vesta/skills/<name>/scripts/` (or Python modules at skill root)
3. If it needs API keys or auth, create `~/vesta/skills/<name>/SETUP.md`
4. If the app needs HTTP access, build an HTTP server + register in `SKILL_SERVERS`
5. If it needs a daemon, build a CLI package under `cli/`
6. Restart with `restart_vesta` to load the new skill
