---
name: home-assistant
description: This skill should be used when the user asks about "home", "house", "energy", "power", "temperature", "climate", "weather", "security", "cameras", "motion", "alarm", "location", "where am I", "battery", or needs to interact with Home Assistant devices, sensors, or automations. No daemon required. queries HA API on demand.
---

# Home Assistant. CLI: ha

## Quick Reference
```bash
ha state sensor.temperature          # get entity state (compact)
ha state sensor.temperature --full   # with all attributes
ha states --domain sensor            # list all sensors
ha states --search kitchen           # search by name
ha history sensor.power --hours 6    # state history
ha weather                           # forecast + sun times
ha service switch turn_on --entity-id switch.my_switch  # call service
ha ping                              # check API connectivity
```

## Commands

### Entity Commands
- `ha state <entity_id>`. get current state (compact). Add `--full` for all attributes
- `ha states`. list all entities. Filter with `--domain <domain>` or `--search <query>`
- `ha history <entity_id>`. state history. Default 24h, override with `--hours N`

### Weather
- `ha weather`. condition, temperature, humidity, wind, sunrise/sunset

### Service Commands
- `ha service <domain> <service>`. call any HA service
  - `--entity-id <id>`. target entity
  - `--data '{"key": "value"}'`. JSON payload

### Connectivity
- `ha ping`. verify API connection

## Setup
```bash
# Requires environment variables:
#   HASS_TOKEN . long-lived access token from HA
#   HASS_URL   . HA base URL (default: http://homeassistant.local:8123)
source /etc/environment
uv tool install ~/vesta/skills/home-assistant/cli
```

## Usage Tips

Use `ha states --domain <domain>` and `ha states --search <query>` to discover entities in the user's HA instance. Common domains: `sensor`, `binary_sensor`, `switch`, `light`, `climate`, `alarm_control_panel`, `person`, `weather`, `camera`, `todo`.

Once you know the entity IDs, use `ha state <entity_id>` to read values and `ha service <domain> <action>` to control devices.
