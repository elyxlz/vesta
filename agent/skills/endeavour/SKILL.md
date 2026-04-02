---
name: endeavour
description: This skill should be used when the user asks about "plex", "movies", "tv shows", "torrents", "downloads", "qbittorrent", "media", "streaming", "endeavour", or needs to search for, download, or browse their media library.
---

# Endeavour — Plex & Torrent Management

A home media server skill combining Plex library management with qBittorrent downloads and torrent site searching.

## Configuration

Set these environment variables (or update the values in the `qb` script):

```bash
ENDEAVOUR_SSH_HOST=<MEDIA_SERVER_HOST>      # e.g. 192.168.1.100 or your.server.example.com
ENDEAVOUR_SSH_PORT=<MEDIA_SERVER_SSH_PORT>  # e.g. 22
ENDEAVOUR_SSH_USER=<MEDIA_SERVER_SSH_USER>  # e.g. mediauser
QB_PORT=<QB_PORT>                           # qBittorrent WebUI port, e.g. 8080
PLEX_MEDIA_ROOT=<PLEX_MEDIA_ROOT>          # e.g. /media/Plex
```

Vesta's SSH key should be pre-installed on the media server. No password needed.

## Connection

```bash
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST>
```

## qBittorrent

One or more qBittorrent instances may be running on your media server. Configure the port and authentication to match your setup.

**Default save path:** `<PLEX_MEDIA_ROOT>`

### API

Run all commands on the media server via SSH:

```bash
# Check version
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s 'http://localhost:<QB_PORT>/api/v2/app/version'"

# List all torrents (JSON)
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s 'http://localhost:<QB_PORT>/api/v2/torrents/info'"

# List active downloads only
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s 'http://localhost:<QB_PORT>/api/v2/torrents/info?filter=downloading'"

# Add torrent by URL (magnet or .torrent URL)
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s -X POST 'http://localhost:<QB_PORT>/api/v2/torrents/add' \
  -F 'urls=magnet:?xt=urn:btih:...' \
  -F 'savepath=<PLEX_MEDIA_ROOT>/Movies'"

# Add torrent by uploading .torrent file
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s -X POST 'http://localhost:<QB_PORT>/api/v2/torrents/add' \
  -F 'torrents=@/path/to/file.torrent' \
  -F 'savepath=<PLEX_MEDIA_ROOT>/Movies'"

# Pause torrent
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s -X POST 'http://localhost:<QB_PORT>/api/v2/torrents/stop' -d 'hashes=HASH'"

# Resume torrent
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s -X POST 'http://localhost:<QB_PORT>/api/v2/torrents/start' -d 'hashes=HASH'"

# Delete torrent (keep files)
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s -X POST 'http://localhost:<QB_PORT>/api/v2/torrents/delete' -d 'hashes=HASH&deleteFiles=false'"

# Delete torrent + files
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s -X POST 'http://localhost:<QB_PORT>/api/v2/torrents/delete' -d 'hashes=HASH&deleteFiles=true'"

# Get torrent properties
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s 'http://localhost:<QB_PORT>/api/v2/torrents/properties?hash=HASH'"
```

### Use the `qb` wrapper script

A helper script is included at `agent/skills/endeavour/qb`. Configure it with your server details, then run:

```bash
/path/to/skills/endeavour/qb status
/path/to/skills/endeavour/qb add "magnet:?xt=..."
/path/to/skills/endeavour/qb add "magnet:?xt=..." --path <PLEX_MEDIA_ROOT>/Movies
/path/to/skills/endeavour/qb ls
/path/to/skills/endeavour/qb ls movies    # filter by name/path keyword
```

## Torrent Site Search

Configure your torrent tracker credentials in the `qb` script or as environment variables:

```bash
TRACKER_USERNAME=<TRACKER_USERNAME>
TRACKER_PASSWORD=<TRACKER_PASSWORD>
TRACKER_URL=<TRACKER_URL>         # e.g. https://www.example-tracker.org
TRACKER_USER_ID=<TRACKER_USER_ID>
```

**Proxy (optional, recommended for privacy):**

```bash
PROXY_HOST=<PROXY_HOST>           # e.g. vpn.example.com
PROXY_PORT=<PROXY_PORT>           # e.g. 1080
PROXY_USER=<PROXY_USER>
PROXY_PASS=<PROXY_PASS>
```

### Tracker Search API

Many trackers provide a JSON API. Example search pattern:

```bash
# Search via qBittorrent's built-in search API (uses installed search plugins)
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s -X POST 'http://localhost:<QB_PORT>/api/v2/search/start' \
  -d 'pattern=blade+runner&plugins=<TRACKER_PLUGIN>&category=movies'"

# Get search results (use the ID returned above)
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s 'http://localhost:<QB_PORT>/api/v2/search/results?id=SEARCH_ID&limit=20&offset=0'"

# Stop search
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s -X POST 'http://localhost:<QB_PORT>/api/v2/search/stop' -d 'id=SEARCH_ID'"
```

**Note:** qBittorrent search plugins may be listed as `enabled: false` in the API but still work when called via `/api/v2/search/start` specifying the plugin name directly.

**Typical torrent download URL format:**
```
<TRACKER_URL>/download/{fid}/{filename}
```
May require session cookies for authentication.

### Tracker Cookies (for direct API calls)

If using cookie-based auth for direct tracker API calls, cache cookies in a local file and pass them with `-b`:

```bash
# Search directly with cookies + proxy
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> \
  'curl -s -b "<TRACKER_SESSION_COOKIE>" \
  --proxy socks5://<PROXY_USER>:<PROXY_PASS>@<PROXY_HOST>:<PROXY_PORT> \
  "<TRACKER_URL>/torrents/browse/list/query/SEARCH+TERMS/categories/CATEGORY_IDS/orderby/seeders/order/desc"'
```

## Media Library

**Location:** `<PLEX_MEDIA_ROOT>/`

Configure your library structure to match your Plex setup. A typical layout:

```
<PLEX_MEDIA_ROOT>/
├── Movies/
└── TVShows/
```

Or per-user libraries:

```
<PLEX_MEDIA_ROOT>/
├── User1/
│   ├── Movies/
│   └── TVShows/
└── User2/
    ├── Movies/
    └── TVShows/
```

## Checking Download Progress

```bash
# Quick status check — shows name, progress, state, speed
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "curl -s 'http://localhost:<QB_PORT>/api/v2/torrents/info' | python3 -c \"
import json, sys
data = json.load(sys.stdin)
active = [t for t in data if t['state'] not in ['stoppedUP']]
print(f'Active: {len(active)} / Total: {len(data)}')
for t in active:
    pct = t['progress'] * 100
    dl = t['dlspeed'] // 1024
    eta_min = t['eta'] // 60 if t['eta'] < 8640000 else -1
    print(f'{t[\\\"state\\\"]}: {pct:.1f}% | {dl}KB/s | ETA: {eta_min}min | {t[\\\"name\\\"][:60]}')
\""
```

## Browsing the Library

```bash
# List movies
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "ls <PLEX_MEDIA_ROOT>/Movies/"

# List TV shows
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "ls <PLEX_MEDIA_ROOT>/TVShows/"

# Search for a title
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "find <PLEX_MEDIA_ROOT>/ -iname '*keyword*' 2>/dev/null"

# Check disk space
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> "df -h <PLEX_MEDIA_ROOT>/"
```

## Workflow: Add a New Torrent

**Recommended approach when qBittorrent's built-in search is unreliable:**

1. **Search** the tracker directly with cookies + proxy:
```bash
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> \
  'curl -s -b "<TRACKER_SESSION_COOKIE>" \
  --proxy socks5://<PROXY_USER>:<PROXY_PASS>@<PROXY_HOST>:<PROXY_PORT> \
  "<TRACKER_URL>/torrents/browse/list/query/SEARCH+TERMS/categories/CATEGORY_IDS/orderby/seeders/order/desc"'
```

2. **Download the .torrent file** via proxy:
```bash
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> \
  "curl -s -o /tmp/movie.torrent \
  -b '<TRACKER_SESSION_COOKIE>' \
  --proxy socks5://<PROXY_USER>:<PROXY_PASS>@<PROXY_HOST>:<PROXY_PORT> \
  '<TRACKER_URL>/download/FID/FILENAME.torrent'"
```

3. **Upload** the .torrent file to qBittorrent:
```bash
ssh -p <MEDIA_SERVER_SSH_PORT> <MEDIA_SERVER_SSH_USER>@<MEDIA_SERVER_HOST> \
  "curl -s -X POST 'http://localhost:<QB_PORT>/api/v2/torrents/add' \
  -F 'torrents=@/tmp/movie.torrent' \
  -F 'savepath=<PLEX_MEDIA_ROOT>/Movies'"
```

4. Monitor progress with `qb status`

## Troubleshooting

**qBittorrent WebUI returns Forbidden from localhost:** Check that `WebUI\LocalHostAuth=false` is set, or add your host to `WebUI\AuthSubnetWhitelist`. Restart the qbittorrent service if needed:
```bash
sudo systemctl restart qbittorrent-nox@<QB_USER>
```

**Tracker cookies expired:** Delete the cached cookie file and trigger a search — the plugin will re-authenticate with the username/password from its config file.

**Multiple qBittorrent instances:** If running multiple instances, use the port of the primary instance with all history. Avoid secondary instances unless specifically needed.
