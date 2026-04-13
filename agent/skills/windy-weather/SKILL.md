---
name: windy-weather
description: Use this skill when the user asks about "weather", "forecast", "will it rain", "temperature", "wind", "humidity", or needs current or upcoming weather conditions for any location. Powered by the Windy Point Forecast API.
---

# Windy Weather Skill

Use this skill when the user asks about weather, forecasts, "will it rain", "what's the temperature", etc.

## Usage

```bash
weather                        # Auto-detect location from HA, show forecast
weather --location london      # Named location
weather --lat 51.5 --lon -0.1  # Specific coordinates
weather --hours 24             # Show next 24 hours (default: 12)
```

## Features

- **Auto-location**: Uses Home Assistant GPS to detect current position — no need to ask where the user is
- **GFS model**: Global forecast data from Windy API with 3-hour resolution
- **Parameters**: Temperature, precipitation, wind speed/direction, humidity
- **Smart summary**: Returns a human-readable summary, not raw data

## Setup

1. Get a free API key from https://api.windy.com (Point Forecast API)
2. Add `WINDY_API_KEY=<your-key>` to `/etc/environment`

## Notes

- Requires a [Windy API key](https://api.windy.com) — free tier available
- Auto-location requires Home Assistant with a GPS-reporting device; use `--lat`/`--lon` as fallback
- Always present temperatures in Celsius and wind in km/h
- Always state the location used (auto-detected or specified)
- Convert UTC timestamps to the user's local timezone
