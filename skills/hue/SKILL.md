---
name: hue
description: This skill should be used when the user asks about "lights", "hue", "philips", "lamp", "bright", "dim", "scene", "room", "colour", "color", or needs to control smart lights, set scenes, adjust brightness, or change light colours.
---

# Philips Hue Smart Lights

Controls Philips Hue lights via the Hue Bridge API v1.

## Connection

- **Bridge IP:** `$HUE_BRIDGE_IP`
- **API Key:** `$HUE_API_KEY`
- **API Base:** `https://$HUE_BRIDGE_IP/api/$HUE_API_KEY/`

Set `HUE_BRIDGE_IP` and `HUE_API_KEY` in your environment (e.g. via `.env` or secrets config).

## CLI

```bash
~/agent/skills/hue/hue status                # Overview of all rooms and their state
~/agent/skills/hue/hue rooms                 # List all rooms with lights and state
~/agent/skills/hue/hue lights                # List all lights with state
~/agent/skills/hue/hue on [room|light]       # Turn on (default: all)
~/agent/skills/hue/hue off [room|light]      # Turn off (default: all)
~/agent/skills/hue/hue dim 50 [room|light]   # Set brightness to 50% (1-100)
~/agent/skills/hue/hue color red [room|light]   # Set colour by name or hex
~/agent/skills/hue/hue scene cinema [room]   # Activate a scene (fuzzy match)
~/agent/skills/hue/hue scenes [room]         # List available scenes
```

Room and scene names support fuzzy matching (e.g. "living" matches "Living room", "bed" matches "Bedroom").

## Setup

1. Find your Hue Bridge IP (check your router or the Hue app).
2. Create an API key by pressing the bridge button and running:
   ```bash
   curl -X POST -d '{"devicetype":"vesta#agent"}' http://<bridge-ip>/api
   ```
3. Set `HUE_BRIDGE_IP` and `HUE_API_KEY` in your environment.
4. Run `~/agent/skills/hue/hue status` to verify connectivity.

## Colour Names

Supported colour names: red, blue, green, yellow, orange, purple, pink, cyan, warm, cool, white, warmwhite, coolwhite. Hex codes also supported (e.g. `#FF5500` or `FF5500`).

## Examples

```bash
# Turn off the bedroom
~/agent/skills/hue/hue off bedroom

# Set living room to cinema scene
~/agent/skills/hue/hue scene cinema living

# Dim the office to 30%
~/agent/skills/hue/hue dim 30 office

# Set all lights to warm white
~/agent/skills/hue/hue color warm

# Check what's on
~/agent/skills/hue/hue status
```
