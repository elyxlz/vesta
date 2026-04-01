---
name: home-assistant
description: This skill should be used when the user asks about "home", "house", "energy", "power", "temperature", "climate", "weather", "security", "cameras", "motion", "alarm", "location", "where am I", "battery", or needs to interact with Home Assistant devices, sensors, or automations. Also use for morning briefings (home overview). No daemon required — queries HA API on demand.
---

# Home Assistant — CLI: ha

## Quick Reference
```bash
ha home                              # full overview (energy + climate + weather + security + location)
ha energy                            # daily/total kWh + current watts
ha location                          # Lucio's GPS + phone battery
ha climate                           # indoor/outdoor temp, humidity, CO2
ha weather                           # forecast, sun times
ha security                          # alarm states + motion sensors
ha state sensor.daily_energy_so_ai   # any entity state
ha state sensor.bedroom_temperature --full  # with all attributes
ha states --domain sensor            # list all sensors
ha states --search studio            # search by name
ha history sensor.generale_power --hours 6  # state history
ha service switch turn_on --entity-id switch.casa_so_ai  # call service
ha ping                              # check API connectivity
```

## Commands

### Overview Commands
- `ha home` — combined overview: energy, climate, weather, security, location. Use for morning briefings
- `ha energy` — daily kWh, total kWh, current watts, last reset time
- `ha location` — GPS coordinates, Google Maps link, phone battery/charging status
- `ha climate` — outdoor + bedroom + living room + studio (temp, humidity, CO2, noise, pressure)
- `ha weather` — condition, temperature, humidity, wind, sunrise/sunset
- `ha security` — Blink alarm panel states + any active motion sensors

### Entity Commands
- `ha state <entity_id>` — get current state (compact). Add `--full` for all attributes
- `ha states` — list all entities. Filter with `--domain <domain>` or `--search <query>`
- `ha history <entity_id>` — state history. Default 24h, override with `--hours N`

### Service Commands
- `ha service <domain> <service>` — call any HA service
  - `--entity-id <id>` — target entity
  - `--data '{"key": "value"}'` — JSON payload

### Connectivity
- `ha ping` — verify API connection

## Setup
```bash
# Requires HASS_TOKEN in environment (already in /etc/environment)
source /etc/environment
uv tool install ~/vesta/skills/home-assistant/cli
```

## Key Entities at So'Ai

### Energy
- `sensor.daily_energy_so_ai` — daily consumption (kWh)
- `sensor.energy_total_so_ai` — running total (kWh)
- `sensor.generale_power` — current draw (W)
- `sensor.prese_power` — outlet power (W)

### Climate (Netatmo)
- Outdoor: `sensor.bedroom_unknown_02_00_00_af_77_10_temperature/humidity`
- Bedroom: `sensor.bedroom_temperature/humidity/carbon_dioxide/noise`
- Living room: `sensor.bedroom_living_room_sensor_temperature/humidity/carbon_dioxide`
- Studio: `sensor.bedroom_studio_temperature/humidity/carbon_dioxide`

### Location
- `person.lucio_pascarelli` — home/not_home + GPS
- `sensor.lps_brick_s25_ultra_battery_level` — phone battery

### Security (Blink)
- 3 alarm panels: cantinetta, sopra, sotto
- ~20 cameras with motion sensors across the property

### Weather
- `weather.forecast_home` — forecast
- `sun.sun` — sun state + rise/set times

### Other
- `todo.shopping_list` — shopping list
- `notify.*` — Echo speakers for announcements
- `switch.casa_so_ai` — main switch

### Patterns
- Morning briefing uses `ha home` for the house section
- Location sharing: Donatella, Elio, and Emilio can ask — respond with Google Maps link from `ha location`
