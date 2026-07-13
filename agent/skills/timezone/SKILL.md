---
name: timezone
description: Set or change the agent's IANA timezone. Use whenever the user relocates, moves, travels, or goes on holiday somewhere on a different timezone, or on first setup when the timezone is still the default `UTC`.
---

# Timezone

The timezone lives in the agent's config store (`~/agent/data/config.json`, key `timezone`). On boot the config object applies it to the process `TZ`, so dates, calendar events, reminders, and `what-day` all read from it. The live value is the `$TZ` env var.

## How to change it

1. Work out the IANA tz (e.g. `Europe/London`, `America/New_York`, `Asia/Tokyo`). Ask if unsure.
2. Write it to the config store (the canonical writer, atomic):
   ```
   cd ~/agent && uv run python -c "from core.config import update_config_store; update_config_store({'timezone': 'Europe/London'})"
   ```
3. Takes effect on the next container restart. Call the `restart_vesta` MCP tool when you want it applied immediately.

## When to use

- First start, if the timezone is still the default `UTC`.
- The user relocates, travels, or holidays on a different timezone.
