---
name: media-server
description: Plex, movies, TV shows, torrents, qBittorrent; download and browse library.
---

# Media Server - Plex & Torrent Management

Home media server running qBittorrent + Plex on a Linux box.

## Quality guidelines

Sensible defaults when downloading:

- **Always ask 1080p or 4K before downloading.** Don't assume; quality preference varies per title and per user.
- **For 4K, target 8GB+ (10GB+ even better).** Smaller "4K" releases are usually re-encoded and lower quality than the size suggests.
- **If 4K isn't available on the tracker**, surface the top-end 1080p options (BluRay 8GB+ or REMUX) and let the user pick. Don't silently fall back to a small 1080p release.

## Connection

```bash
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST
```

Set the following environment variables:
- `MEDIA_SERVER_HOST` - hostname or IP of the media server
- `MEDIA_SERVER_SSH_PORT` - SSH port (e.g. 22)
- `MEDIA_SERVER_USER` - SSH username

Vesta's SSH key should be pre-installed. No password needed once configured.

## qBittorrent

**Default port:** `$QB_PORT` (default: 8888)
**Default save path:** `$PLEX_MEDIA_PATH` (e.g. `/media/Plex`)
**Auth:** Configure `WebUI\LocalHostAuth=false` in qBittorrent settings for localhost access without login.

### API

Run all commands on the media server via SSH:

```bash
# Check version
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s 'http://localhost:$QB_PORT/api/v2/app/version'"

# List all torrents (JSON)
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s 'http://localhost:$QB_PORT/api/v2/torrents/info'"

# List active downloads only
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s 'http://localhost:$QB_PORT/api/v2/torrents/info?filter=downloading'"

# Add torrent by URL (magnet or .torrent URL)
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/torrents/add' \
  -F 'urls=magnet:?xt=urn:btih:...' \
  -F 'savepath=$PLEX_MEDIA_PATH'"

# Add torrent by uploading .torrent file
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/torrents/add' \
  -F 'torrents=@/path/to/file.torrent' \
  -F 'savepath=$PLEX_MEDIA_PATH'"

# Pause torrent
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/torrents/stop' -d 'hashes=HASH'"

# Resume torrent
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/torrents/start' -d 'hashes=HASH'"

# Delete torrent (keep files)
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/torrents/delete' -d 'hashes=HASH&deleteFiles=false'"

# Delete torrent + files
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/torrents/delete' -d 'hashes=HASH&deleteFiles=true'"

# Get torrent properties
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s 'http://localhost:$QB_PORT/api/v2/torrents/properties?hash=HASH'"
```

### Use the `qb` wrapper script

A helper script is available at `~/agent/skills/media-server/qb`. Run it with:

```bash
~/agent/skills/media-server/qb status
~/agent/skills/media-server/qb add "magnet:?xt=..."
~/agent/skills/media-server/qb add "magnet:?xt=..." --path /path/to/save
~/agent/skills/media-server/qb ls
~/agent/skills/media-server/qb ls movies    # filter by save path keyword
```

## Torrent Search

qBittorrent supports search plugins for torrent sites. A TorrentLeech plugin is included.

**Required env vars for tracker search:**
- `TL_USERNAME` - TorrentLeech username
- `TL_PASSWORD` - TorrentLeech password
- `SOCKS5_USER` - SOCKS5 proxy username (e.g. VPN provider)
- `SOCKS5_PASS` - SOCKS5 proxy password
- `SOCKS5_HOST` - SOCKS5 proxy host
- `SOCKS5_PORT` - SOCKS5 proxy port (default: 1080)

**IMPORTANT:** Some ISPs block tracker sites. A SOCKS5 proxy or VPN is required for search to work. Use the **vpn** skill to get the proxy URL:

```bash
PROXY_URL=$(~/agent/skills/vpn/vpn proxy-url)
```

### Search via qBittorrent plugin (preferred)

```bash
~/agent/skills/media-server/qb search "Movie Name" movies
~/agent/skills/media-server/qb search "TV Show" tv
~/agent/skills/media-server/qb search "anything" --plugin torrentleech
```

### Search via standalone tl-search script

```bash
~/agent/skills/media-server/tl-search "Inception 2010" --cat movies
~/agent/skills/media-server/tl-search "Breaking Bad" --cat tv --limit 10
~/agent/skills/media-server/tl-search "Dune 2024" --cat movies --add 1 --path $PLEX_MEDIA_PATH/Movies
~/agent/skills/media-server/tl-search "query" --json   # raw JSON output
```

### Search via qBittorrent API directly

```bash
# Start search
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/search/start' \
  -d 'pattern=SEARCH+TERMS&plugins=torrentleech&category=movies'"

# Get search results (use the ID returned above)
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s 'http://localhost:$QB_PORT/api/v2/search/results?id=SEARCH_ID&limit=20&offset=0'"

# Stop/delete search
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/search/delete' -d 'id=SEARCH_ID'"
```

**Note:** qBittorrent search plugins may appear as `enabled: false` in the API listing but still work when called via `/api/v2/search/start` specifying the plugin name directly.

### Installing the TorrentLeech plugin

```bash
# Plugin source is at ~/agent/skills/media-server/torrentleech.py
# Serve and install via API:
python3 -m http.server 9999 --directory ~/agent/skills/media-server/ &
curl -X POST 'http://localhost:$QB_PORT/api/v2/search/installPlugin' \
  -d 'sources=http://localhost:9999/torrentleech.py'
kill %1
```

### TorrentLeech categories
- **movies:** 1,8,9,10,11,12,13,14,15,29,36,37,43,47
- **tv:** 2,26,27,32,44
- **music:** 16-25
- **games:** 3,33-35,38-42
- **software:** 4,28,30,31
- **anime:** 5,6,7
- **books:** 45,46

## Media Library

**Location:** `$PLEX_MEDIA_PATH`

```
$PLEX_MEDIA_PATH/
├── <User1>/
│   ├── Movies/
│   └── TVShows/
├── <User2>/
│   ├── Movies/
│   └── TVShows/
└── Torrents/     (exported .torrent files archive)
```

## Checking Download Progress

```bash
# Quick status check - shows name, progress, state, speed
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "curl -s 'http://localhost:$QB_PORT/api/v2/torrents/info' | python3 -c \"
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
# List a user's movies
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "ls $PLEX_MEDIA_PATH/<User>/Movies/"

# List a user's TV shows
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "ls $PLEX_MEDIA_PATH/<User>/TVShows/"

# Search for a title
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "find $PLEX_MEDIA_PATH/ -iname '*keyword*' 2>/dev/null"

# Check disk space
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST "df -h $PLEX_MEDIA_PATH/"
```

## Workflow: Add a New Torrent

1. **Search** the tracker directly with cookies + proxy (see Torrent Search section above)
2. **Download the .torrent file** via proxy to the server's `/tmp/`
3. **Upload** the .torrent file to qBittorrent:
```bash
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST \
  "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/torrents/add' \
  -F 'torrents=@/tmp/movie.torrent' \
  -F 'savepath=$PLEX_MEDIA_PATH/<User>/Movies'"
```
4. Monitor progress with `qb status`

## qBittorrent Config Notes

Recommended settings for the main instance:
- `WebUI\LocalHostAuth=false` - no login needed from localhost
- `WebUI\AuthSubnetWhitelist=192.168.0.0/24` - LAN also whitelisted (adjust to your subnet)
- SOCKS5 proxy configured for all torrent traffic (VPN recommended)
- Torrent export dir: `$PLEX_MEDIA_PATH/Torrents`

## Troubleshooting

**WebUI returns Forbidden from localhost:** Ensure `WebUI\LocalHostAuth=false` is set. Restart the service:
```bash
sudo systemctl restart qbittorrent-nox@<QB_USER>
```

**Tracker cookies expired:** Re-login by deleting the cached cookies file and triggering a search (the plugin will re-authenticate).

**Search plugin not finding results:** Even if plugins show `enabled: false`, they still work when called via `/api/v2/search/start` with the plugin name specified directly.
