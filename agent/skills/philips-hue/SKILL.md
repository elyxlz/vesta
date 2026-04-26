---
name: philips-hue
description: This skill should be used when the user asks about "lights", "hue", "philips", "lamp", "bright", "dim", "scene", "room", "colour", "color", or needs to control smart lights, set scenes, adjust brightness, or change light colours.
---

# Philips Hue Smart Lights

Controls Philips Hue lights via the Hue Bridge API v1.

## Connection

Required env vars:

- `HUE_BRIDGE_IP`  IP of the Hue Bridge on your LAN
- `HUE_API_KEY`    API key generated against the bridge (see Setup)

API base: `https://$HUE_BRIDGE_IP/api/$HUE_API_KEY/`. The bridge serves a self-signed cert, so direct `curl` calls need `-k` (the `hue` wrapper already passes it).

## CLI

```bash
~/agent/skills/philips-hue/hue status                # Overview of all rooms and their state
~/agent/skills/philips-hue/hue rooms                 # List all rooms with lights and state
~/agent/skills/philips-hue/hue lights                # List all lights with state
~/agent/skills/philips-hue/hue on [room|light]       # Turn on (default: all)
~/agent/skills/philips-hue/hue off [room|light]      # Turn off (default: all)
~/agent/skills/philips-hue/hue dim 50 [room|light]   # Set brightness to 50% (1-100)
~/agent/skills/philips-hue/hue color red [room|light]   # Set colour by name or hex
~/agent/skills/philips-hue/hue scene cinema [room]   # Activate a scene (fuzzy match)
~/agent/skills/philips-hue/hue scenes [room]         # List available scenes
```

Room and scene names support fuzzy matching (e.g. "living" matches "Living room", "bed" matches "Bedroom").

## Setup

1. **Find the bridge IP.** Check the Hue app (Settings -> Hue Bridges -> tap the bridge), your router's DHCP table, or use mDNS:
   ```bash
   dns-sd -B _hue._tcp .         # macOS
   avahi-browse -tr _hue._tcp    # Linux
   ```
   Reserve a static lease for the bridge in your router so the IP doesn't drift.

2. **Press the bridge link button**, then within ~30 seconds run:
   ```bash
   curl -X POST -d '{"devicetype":"vesta#agent"}' http://<bridge-ip>/api
   ```
   Response is `[{"success":{"username":"<API_KEY>"}}]` on success, or `[{"error":{"description":"link button not pressed"}}]` if you missed the window. Re-press and retry.

3. Set `HUE_BRIDGE_IP` and `HUE_API_KEY` in your environment.

4. Verify: `~/agent/skills/philips-hue/hue status`

## Colours

Built-in names: red, blue, green, yellow, orange, purple, pink, cyan, warm, cool, white, warmwhite, coolwhite. Hex codes also work (e.g. `#FF5500` or `FF5500`).

**Anything outside the built-in list, you translate to hex yourself.** If the user says "sunset", "candlelight", "deep ocean", "lavender mist", "Halloween orange", pick a hex that fits and pass it directly:

```bash
~/agent/skills/philips-hue/hue color "#FF7E50" living    # sunset
~/agent/skills/philips-hue/hue color "#FFB347" bedroom   # candlelight
~/agent/skills/philips-hue/hue color "#0B3D5C" office    # deep ocean
```

Mirror the mood the user described. They shouldn't have to know hex.

## Examples

```bash
# Turn off the bedroom
~/agent/skills/philips-hue/hue off bedroom

# Set living room to cinema scene
~/agent/skills/philips-hue/hue scene cinema living

# Dim the office to 30%
~/agent/skills/philips-hue/hue dim 30 office

# Set all lights to warm white
~/agent/skills/philips-hue/hue color warm

# Check what's on
~/agent/skills/philips-hue/hue status
```

## Troubleshooting

**Connection refused / no response.** Bridge IP probably changed (DHCP). Re-discover via mDNS (see Setup) and update `HUE_BRIDGE_IP`. Reserve a static lease to avoid this.

**`unauthorized user`.** API key is invalid or was wiped (factory reset, deleted from the app). Re-run the Setup curl to mint a fresh key.

**`link button not pressed`.** You missed the ~30s window after pressing the bridge button. Press it again and retry the curl immediately.

**Cert errors on direct curl.** The bridge serves a self-signed cert; pass `-k`. The `hue` wrapper handles this for you.

**Room or scene not matching.** Fuzzy match is case-insensitive substring. Run `hue rooms` or `hue scenes` to see exact names; if multiple match, the first wins.

**Commands succeed but the lights don't react.** The bulb is powered off at the wall switch. Hue bulbs need mains power to receive commands; if everything in `hue status` looks healthy and the API returns success, ask the user to flip the physical switch back on.
