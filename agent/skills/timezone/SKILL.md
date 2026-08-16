---
name: timezone
description: Set or change the agent's IANA timezone. Use whenever the user relocates, moves, travels, or goes on holiday somewhere on a different timezone, when a `source=vestad` `type=user-timezone` notification arrives, or on first setup when the timezone is still the default `UTC`.
---

# Timezone

The timezone lives in the agent's config store (`~/agent/data/config.json`, key `timezone`). On boot the config object applies it to the process `TZ`, so dates, calendar events, reminders, dreams, and `what-day` all read from it. The live value is the `$TZ` env var.

## How to change it

1. Work out the IANA tz (e.g. `Europe/London`, `America/New_York`, `Asia/Tokyo`). Ask if unsure.
2. Write it to the config store (the canonical writer, atomic):
   ```
   cd ~/agent && uv run python -c "from core.config import update_config_store; update_config_store({'timezone': 'Europe/London'})"
   ```
3. Applies on the next restart (`restart_vesta` to apply now).

## How you learn the user moved

The user's devices report where they are, and vestad tells you when that changes:

- `source=vestad` `type=user-timezone`: a device the user is on reports a zone that differs from yours. The notification carries `device` (e.g. `Vesta Mobile on iOS`), `device_timezone`, and `agent_timezone`. You get it once per zone per device: it does not repeat while nothing changes, and it starts over when you change your own timezone (a device still on the old zone is news again).
- `source=vestad` `type=user-location`: the phone's macro place changed (city and country), or it moved a long way when no place name was known. The notification carries `place` (e.g. `Tokyo, Japan`), `latitude`, `longitude`, and `accuracy_m`. Only a phone whose owner turned on location sharing in the app sends this.
- The `user_devices` tool lists every device with its current timezone, position, place, and report time, whenever you want to check rather than wait.

Chat channels carry no zone: a WhatsApp or Telegram message tells you nothing about where it was sent from. There, what the user says ("landed in Tokyo") is the signal, as it always is.

The decision is yours, not vestad's. A one-day trip is not a reason to move dreams and reminders; a stay is. When a `user-timezone` notification arrives, check the user's plans (calendar, what they told you) and, if it looks like a stay or you are unsure, ask them briefly before switching. Switching means the steps above plus a `restart_vesta`, so reminders and the nightly dream follow the user.
