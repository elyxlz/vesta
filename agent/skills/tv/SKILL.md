---
name: tv
description: Use for "TV", "Samsung TV", "television", "watch", "play on TV", "YouTube on TV", "volume", "turn on TV", "turn off TV", or any Samsung Smart TV control.
---

# Samsung TV -- Python: samsungtvws

Control a Samsung Smart TV via the WebSocket API.

## TV Info

- **IP**: `<TV_IP>` (see Quick Start for auto-discovery)
- **MAC**: `<TV_MAC>`
- **OS**: Tizen
- **Port**: 8002 (WebSocket API, HTTPS)
- **Token file**: `/root/vesta/data/samsung_tv_token.json`

## Quick Start

**IMPORTANT: Always auto-discover the TV's IP first.** The IP can change after power cycles. Never hardcode a static IP — always check the ARP table for the TV's MAC address.

```python
import subprocess, re

def find_tv_ip(mac='<TV_MAC>'):
    """Find the TV's current IP from the ARP table. Always call this first."""
    arp = open('/proc/net/arp').read()
    best_ip = None
    for line in arp.strip().split('\n')[1:]:
        parts = line.split()
        if len(parts) >= 4 and parts[3].lower() == mac.lower():
            if parts[2] == '0x2':  # valid/reachable entry
                return parts[0]
            best_ip = parts[0]  # fallback to stale entry
    return best_ip

TV_IP = find_tv_ip()
if not TV_IP:
    raise Exception("TV not found on network — may be powered off")

from samsungtvws import SamsungTVWS

tv = SamsungTVWS(
    host=TV_IP,
    port=8002,
    name='Vesta',
    timeout=15,
    token_file='/root/vesta/data/samsung_tv_token.json'
)
```

Always use `uv run python` to run scripts.

## Wake-on-LAN

The TV can be woken from standby via a magic packet. If the TV is off (ports 8001/8002 not responding), send WoL first and wait ~10 seconds.

```python
import socket

mac = '<TV_MAC>'
mac_bytes = bytes.fromhex(mac.replace(':', ''))
magic_packet = b'\xff' * 6 + mac_bytes * 16

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sock.sendto(magic_packet, ('255.255.255.255', 9))
sock.close()
```

## Power & Device Info

```python
# Check if TV is reachable
tv.is_alive()  # returns bool

# Get device info (REST, no WebSocket needed)
info = tv.rest_device_info()
# info['device']['PowerState'] -> 'on' / 'standby'
# info['device']['name'] -> TV model name

# Power off (via key)
tv.send_key('KEY_POWER')

# Power on -> use Wake-on-LAN (above)
```

## Remote Control Keys

```python
# Send a single key
tv.send_key('KEY_VOLUP')

# Send a key multiple times
tv.send_key('KEY_VOLUP', times=5)

# Hold a key for N seconds
tv.hold_key('KEY_POWER', seconds=3)
```

### Common Keys

| Key | Action |
|-----|--------|
| `KEY_POWER` | Power toggle |
| `KEY_VOLUP` / `KEY_VOLDOWN` | Volume up/down |
| `KEY_MUTE` | Mute toggle |
| `KEY_UP` / `KEY_DOWN` / `KEY_LEFT` / `KEY_RIGHT` | D-pad navigation |
| `KEY_ENTER` | Select/confirm |
| `KEY_RETURN` | Back |
| `KEY_HOME` | Home screen |
| `KEY_SOURCE` | Input source |
| `KEY_MENU` | Menu |
| `KEY_INFO` | Info overlay |
| `KEY_GUIDE` | TV guide |
| `KEY_CHUP` / `KEY_CHDOWN` | Channel up/down |
| `KEY_PLAY` / `KEY_PAUSE` / `KEY_STOP` | Playback control |
| `KEY_REWIND` / `KEY_FF` | Rewind/fast forward |
| `KEY_RED` / `KEY_GREEN` / `KEY_YELLOW` / `KEY_BLUE` | Color buttons |
| `KEY_0` to `KEY_9` | Number keys |
| `KEY_HDMI1` to `KEY_HDMI4` | HDMI inputs |

### Shortcut Methods

```python
sc = tv.shortcuts()
sc.power()
sc.volume_up()
sc.volume_down()
sc.mute()
sc.up() / sc.down() / sc.left() / sc.right()
sc.enter()
sc.back()
sc.home()
sc.source()
sc.menu()
sc.guide()
sc.info()
sc.channel_up() / sc.channel_down()
sc.channel(number)
sc.digit(n)
sc.red() / sc.green() / sc.yellow() / sc.blue()
```

## Apps

### App Management

```python
# List installed apps (uses WebSocket, may be slow)
apps = tv.app_list()

# Run an app (REST)
tv.rest_app_run('APP_ID')

# Run an app with deep link (WebSocket)
tv.run_app('APP_ID', app_type='DEEP_LINK', meta_tag='payload')

# Check app status
status = tv.rest_app_status('APP_ID')
# -> {'id': '...', 'name': '...', 'running': True/False, 'visible': True/False, 'version': '...'}

# Close an app
tv.rest_app_close('APP_ID')

# Install an app
tv.rest_app_install('APP_ID')
```

### Known App IDs

| App | ID |
|-----|-----|
| YouTube | `111299001912` |
| Netflix | `3201907018807` |
| Prime Video | `3201910019365` |
| Disney+ | `3201901017640` |
| Apple TV | `3201807016597` |
| Spotify | `3201606009684` |
| Samsung TV Plus | `3201710015037` |
| Plex | `3201512006963` |

## YouTube

### Launch YouTube (home screen)

```python
tv.rest_app_run('111299001912')
```

YouTube must be running before casting via the Lounge API. Launch it with the above command and wait a few seconds if it is not already open.

### Play a Specific Video (YouTube Lounge API) -- WORKING METHOD

The Lounge API uses DIAL on port 8080 to get the screen ID, then the YouTube Lounge API at youtube.com to create a remote-control session and send a `setPlaylist` command.

**Note:** This casts as a "guest" session, which means ads will play.

**Prerequisite:** YouTube must be running on the TV. Launch it first if needed:

```python
tv.rest_app_run('111299001912')
import time; time.sleep(5)
```

#### Preferred method: pyytlounge (pip: pyytlounge)

The `pyytlounge` library wraps the Lounge API and provides playback control, event listening, and session management. This is the recommended approach.

**Auth persistence:** The Lounge API auth state is saved to `/root/vesta/data/youtube_lounge_auth.json` after first successful pairing. On subsequent runs, the saved `screen_id` is used to refresh the lounge token without triggering the TV pairing popup. Only falls back to full `pair_with_screen_id()` if the saved state is invalid.

```python
import asyncio, json, os, requests, xml.etree.ElementTree as ET
from pyytlounge import YtLoungeApi

TV_IP = find_tv_ip()  # use auto-discovery above
AUTH_FILE = "/root/vesta/data/youtube_lounge_auth.json"

def get_screen_id():
    """Get YouTube screen ID from TV's DIAL service on port 8080."""
    resp = requests.get(f"http://{TV_IP}:8080/ws/apps/YouTube", timeout=5)
    root = ET.fromstring(resp.text)
    ns = {'dial': 'urn:dial-multiscreen-org:schemas:dial'}
    additional = root.find('.//dial:additionalData', ns)
    for child in (additional if additional is not None else []):
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'screenId':
            return child.text
    return None

def save_auth(api):
    """Save auth state after successful connection."""
    data = api.auth.serialize()
    os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
    with open(AUTH_FILE, 'w') as f:
        json.dump(data, f)

def load_auth(api):
    """Load saved auth state. Returns True if loaded successfully."""
    try:
        with open(AUTH_FILE) as f:
            data = json.load(f)
        api.auth.deserialize(data)
        return bool(api.auth.screen_id)
    except (FileNotFoundError, json.JSONDecodeError, Exception):
        return False

async def play_youtube_video(video_id: str):
    """Play a YouTube video on the TV via the Lounge API."""
    async with YtLoungeApi("Vesta") as api:
        connected = False
        # Try restoring saved auth (avoids TV pairing popup)
        if load_auth(api):
            try:
                await api.refresh_auth()  # refreshes lounge token from screen_id, no popup
                connected = await api.connect()
            except Exception:
                connected = False
        # Fallback: full pairing flow (will show TV popup on first use)
        if not connected:
            screen_id = get_screen_id()
            if not screen_id:
                raise Exception("YouTube not running on TV or DIAL unavailable")
            await api.pair_with_screen_id(screen_id)
            connected = await api.connect()
        if connected:
            save_auth(api)
            await api.play_video(video_id)
        else:
            raise Exception("Failed to connect to YouTube Lounge")

# Usage:
asyncio.run(play_youtube_video("VIDEO_ID"))
```

**Notes on auth persistence:**
- `screen_id` is stable as long as YouTube stays running on the TV. If YouTube restarts, a new screen_id is fetched via DIAL automatically.
- `refresh_auth()` only needs `screen_id` — it's a server-side call, no TV popup.
- The popup only fires when `connect()` creates a brand-new session with an unknown device.
- Use `api.auth.serialize()` / `api.auth.deserialize()` (NOT `store_auth_state()` which has a key naming bug in v3.2.0).
- If saved auth fails, the code gracefully falls back to full pairing.

Additional pyytlounge commands (after connect):

```python
await api.pause()                        # Pause playback
await api.play()                         # Resume playback
await api.seek_to(120.0)                 # Seek to 2 minutes
await api.next()                         # Next video in queue
await api.previous()                     # Previous video
await api.skip_ad()                      # Skip ad if possible
await api.set_volume(50)                 # Set volume (0-100)
await api.set_playback_speed(1.5)        # Playback speed (0.25-2)
await api.get_now_playing()              # Request current state
await api.disconnect()                   # Clean disconnect
```

#### Alternative: raw requests (no extra dependencies)

```python
"""YouTube Lounge API - Cast a specific video to the TV's YouTube app"""
import requests, re, xml.etree.ElementTree as ET

TV_IP = find_tv_ip()  # use auto-discovery above

def cast_youtube_video(video_id: str):
    """Cast a YouTube video to the Samsung TV via YouTube Lounge API."""
    # Step 1: Get screen ID from DIAL
    resp = requests.get(f"http://{TV_IP}:8080/ws/apps/YouTube", timeout=5)
    root = ET.fromstring(resp.text)
    ns = {'dial': 'urn:dial-multiscreen-org:schemas:dial'}
    additional = root.find('.//dial:additionalData', ns)
    screen_id = None
    for child in (additional if additional is not None else []):
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'screenId':
            screen_id = child.text
            break

    # Step 2: Get lounge token
    resp = requests.post(
        "https://www.youtube.com/api/lounge/pairing/get_lounge_token_batch",
        data={"screen_ids": screen_id}
    )
    lounge_token = resp.json()["screens"][0]["loungeToken"]

    # Step 3: Create session
    BIND_URL = "https://www.youtube.com/api/lounge/bc/bind"
    session_params = {
        "CVER": "1", "RID": "1", "VER": "8",
        "app": "youtube-desktop", "device": "REMOTE_CONTROL",
        "id": "vesta-cast", "loungeIdToken": lounge_token, "name": "Vesta",
    }
    resp = requests.post(BIND_URL, params=session_params, data={"count": "0"})
    sid = re.search(r'\["c","([^"]+)"', resp.text)
    gsession = re.search(r'\["S","([^"]+)"', resp.text)
    sid = sid.group(1) if sid else None
    gsessionid = gsession.group(1) if gsession else None

    if not sid or not gsessionid:
        raise Exception("Failed to create Lounge session")

    # Step 4: Send setPlaylist to play video
    play_params = {
        "CVER": "1", "RID": "2", "VER": "8",
        "SID": sid, "gsessionid": gsessionid,
        "app": "youtube-desktop", "device": "REMOTE_CONTROL",
        "id": "vesta-cast", "loungeIdToken": lounge_token, "name": "Vesta",
    }
    play_data = {
        "count": "1",
        "req0__sc": "setPlaylist",
        "req0_videoId": video_id,
        "req0_videoIds": video_id,
        "req0_currentTime": "0",
        "req0_currentIndex": "0",
    }
    resp = requests.post(BIND_URL, params=play_params, data=play_data)
    return resp.status_code == 200
```

### Finding a YouTube Video ID

To search YouTube and extract video IDs:

```bash
curl -s "https://www.youtube.com/results?search_query=QUERY" -H "User-Agent: Mozilla/5.0" | grep -oP '"videoId":"[^"]+' | head -5
```

Replace `QUERY` with a URL-encoded search term (e.g., `lo+fi+beats`). Each result gives `"videoId":"XXXXXXXXXXX"` -- extract the 11-character ID.

### Deep Link Method -- may not work on all models

The `DEEP_LINK` / `run_app` method does not work on all Samsung TV models. Use the Lounge API above for reliable video casting.

```python
# May NOT work on all models -- use the Lounge API above instead
video_id = "VIDEO_ID"
tv.run_app('111299001912', app_type='DEEP_LINK', meta_tag=f'v={video_id}')
```

### YouTube Playback Control

Once a video is playing, you can control it via the Lounge API (see pyytlounge commands above) or via remote keys:

```python
tv.send_key('KEY_PLAY')    # Play
tv.send_key('KEY_PAUSE')   # Pause
tv.send_key('KEY_RETURN')  # Back (exit video, return to YouTube browse)
```

## Browser

```python
# Open any URL in the TV's built-in browser
tv.open_browser('https://example.com')

# Open a YouTube video in the browser (fallback method)
tv.open_browser('https://www.youtube.com/watch?v=VIDEO_ID')
```

## Text Input

```python
# Type text (when a text field is focused)
tv.send_text('search query')

# Clear text input
tv.end_text()
```

## Cursor Control

```python
# Move cursor to x, y position (for pointer-based UIs)
tv.move_cursor(x=500, y=300, duration=0)
```

## Setup

1. Install the Python library: `uv add samsungtvws`
2. Set `<TV_MAC>` to your TV's MAC address (found in TV Settings > General > Network > Network Status)
3. On first WebSocket connection, approve the pairing request on the TV screen
4. The token is saved to `/root/vesta/data/samsung_tv_token.json` for subsequent connections

## Notes

- The TV must be on the same local network as Vesta
- First WebSocket connection may require user approval on the TV screen
- Token is saved to `/root/vesta/data/samsung_tv_token.json` after first successful connection
- REST API calls (rest_*) work without WebSocket -- useful for status checks
- WebSocket calls (send_key, run_app, open_browser) require an active connection
- If WebSocket times out, the TV may have gone to sleep -- send WoL first
- The TV auto-sleeps after inactivity; WoL brings it back in ~10 seconds
- Port 9197 is UPnP/SOAP (DLNA renderer), not useful for app control
- **DHCP IP changes**: The TV's IP can change after power cycles. If connection fails, check the ARP table (`cat /proc/net/arp`) and look for the TV's MAC to find the current IP. The `find_tv_ip()` helper handles this automatically.
- **Don't blindly navigate YouTube UI with remote keys** (KEY_UP/DOWN/LEFT/RIGHT). You can't see the screen, so you'll end up in the wrong place. Use the Lounge API for playback control (play, pause, seek). KEY_CC does not reliably toggle subtitles on all models.
- **Spotify on TV**: Launch Spotify app (`rest_app_run('3201606009684')`), then use the Spotify playback API with the TV device ID to control what plays. This is more reliable than remote keys.
