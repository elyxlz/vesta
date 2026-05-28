---
name: timezone
description: Set or change the agent's IANA timezone. Use whenever the user relocates, moves, travels, or goes on holiday somewhere on a different timezone, or on first setup when `$TZ` is not set yet.
---

# Timezone

`TZ` lives in `~/.bashrc` as `export TZ=<IANA tz>`. Sourced at container start and on every interactive shell, so dates, calendar events, reminders, and `what-day` all read from it.

## How to change it

1. Work out the IANA tz (e.g. `Europe/London`, `America/New_York`, `Asia/Tokyo`). Ask if unsure.
2. `Edit` `~/.bashrc`. Drop any existing line starting with `export TZ=`, then append `export TZ=<tz>` at the bottom.
3. Takes effect on the next container restart. Call the `restart_vesta` MCP tool when you want it applied immediately.

## When to use

- First start, if `$TZ` is not already set.
- The user relocates, moves, travels, or goes on holiday somewhere on a different timezone.
