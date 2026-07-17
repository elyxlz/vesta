---
name: wx
description: Quick one-line weather for any location, no API key needed (open-meteo). Good default for a morning brief or a fast "what's it doing outside".
---

# wx

Keyless weather via [open-meteo](https://open-meteo.com). Prints a single human-readable line: current conditions, today's high/low, rain chance, wind. No API key, no account, no config. Use it when you want a fast forecast and don't have (or don't need) the `windy-weather` key.

## Setup

```bash
install -m 755 ~/agent/skills/wx/wx.py ~/.local/bin/wx
```

Make sure `~/.local/bin` is on `PATH` (it is by default in the container).

## Usage

```bash
wx                 # default London
wx Rome            # any place name (geocoded via open-meteo)
wx "New York"      # multi-word places: quote them
```

Example output:

```
Rome: now 28C clear, today 24-37C mostly clear, rain chance 0%, wind 2 km/h
```

## Notes

- Temperatures in Celsius, wind in km/h.
- Place names are resolved with open-meteo's geocoding API; a small built-in table short-circuits common spots.
- Single-day forecast by design (keeps the output to one line). For richer multi-day forecasts or an API-key-based source, use the `windy-weather` skill instead.
