---
name: home-assistant
description: Home Assistant: energy, temperature, cameras, alarms, devices, sensors, automations.
---

# Home Assistant - CLI: ha

## Commands
```bash
ha state sensor.temperature          # get entity state (compact); --full for all attributes
ha states --domain sensor            # list entities by domain
ha states --search kitchen           # search entities by name
ha history sensor.power --hours 6    # state history (default 24h)
ha weather                           # condition, temperature, humidity, wind, sunrise/sunset
ha service switch turn_on --entity-id switch.my_switch  # call any HA service
ha service light turn_on --entity-id light.desk --data '{"brightness": 128}'  # with JSON payload
ha ping                              # verify API connectivity
```

Discover entities with `ha states --domain <domain>` or `--search <query>`; common domains: `sensor`, `binary_sensor`, `switch`, `light`, `climate`, `alarm_control_panel`, `person`, `weather`, `camera`, `todo`. Once you know the entity IDs, read with `ha state` and control with `ha service`.

## Setup
```bash
# Requires environment variables:
#   HASS_TOKEN - long-lived access token from HA
#   HASS_URL   - HA base URL (default: http://homeassistant.local:8123)
source /etc/environment
uv tool install --editable ~/agent/skills/home-assistant/cli
```
