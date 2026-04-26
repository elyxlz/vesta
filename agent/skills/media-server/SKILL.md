---
name: media-server
description: This skill should be used when the user asks about Plex, movies, TV shows, torrents, or downloads: searching trackers, adding torrents, monitoring progress, or browsing the Plex library.
---

# Media Server

Home media server running qBittorrent + Plex on a Linux box, accessed over SSH. Use the `qb` wrapper for everything qBittorrent-related; use plugins under `plugins/<tracker>/` for per-tracker search.

## Connection

Required env vars:

- `MEDIA_SERVER_HOST`     hostname or IP
- `MEDIA_SERVER_SSH_PORT` SSH port (default: 22)
- `MEDIA_SERVER_USER`     SSH username
- `QB_PORT`               qBittorrent WebUI port (default: 8888)
- `PLEX_MEDIA_PATH`       Plex media base path (default: `/media/Plex`)

Vesta's SSH key should be pre-installed; no password needed. Tracker traffic must go through a proxy: pull it from the `vpn` skill rather than reading `SOCKS5_*` directly.

## CLI

```bash
~/agent/skills/media-server/qb status                          # Active/incomplete torrents with progress, speed, ETA
~/agent/skills/media-server/qb ls [filter]                     # List all torrents (filter by name/path keyword)
~/agent/skills/media-server/qb add <url> [--movies|--tv|--path PATH]   # Add by magnet or .torrent URL
~/agent/skills/media-server/qb search <query> [movies|tv|all]  # Search via qBittorrent plugin
~/agent/skills/media-server/qb pause <hash>
~/agent/skills/media-server/qb resume <hash>
~/agent/skills/media-server/qb delete <hash> [--files]         # --files also removes the data
~/agent/skills/media-server/qb info <hash>                     # Properties for a single torrent
~/agent/skills/media-server/qb disk                            # Free space + per-user usage on PLEX_MEDIA_PATH
~/agent/skills/media-server/qb ls-plex [USER] [movies|tv]      # Browse Plex library
~/agent/skills/media-server/qb find <keyword>                  # Find files in PLEX_MEDIA_PATH by name
```

`qb add` accepts URLs (magnets, http(s) `.torrent` URLs) only. For a `.torrent` already on disk, see "Adding a local .torrent" below.

## Library structure

```
$PLEX_MEDIA_PATH/
├── <User1>/
│   ├── Movies/
│   └── TVShows/
├── <User2>/
│   ├── Movies/
│   └── TVShows/
└── Torrents/   (exported .torrent file archive)
```

Route adds with `--movies` / `--tv` shortcuts on `qb add`, or `--path` for anything else.

## Searching trackers

Two paths, both go through the configured proxy:

1. **`qb search <query>`** uses qBittorrent's built-in search API across all installed plugins. Quick, but plugin-dependent.
2. **Per-plugin scrape script** at `plugins/<tracker>/search`. Logs in directly to the tracker, scrapes results, and can add the chosen result to qBittorrent in one call. Use this when `qb search` returns nothing or the plugin is flaky.

Each plugin lives in its own directory with a README covering env vars, categories, and quirks. Currently installed:

- **TorrentLeech**: `plugins/torrentleech/` (see its [README](plugins/torrentleech/README.md))

To add a new tracker, create `plugins/<name>/` with a qBittorrent `.py` plugin and a `search` script following the TorrentLeech layout.

## Adding a local .torrent

`qb add` does not upload local files. When a per-plugin `search` script downloads a `.torrent` to the server (typically `/tmp/`), upload it directly via the qBittorrent API:

```bash
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST \
  "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/torrents/add' \
   -F 'torrents=@/tmp/movie.torrent' \
   -F 'savepath=$PLEX_MEDIA_PATH/<User>/Movies'"
```

Most plugin `search` scripts do this for you with `--add <n> --path <dir>`.

## Examples

```bash
# What's downloading right now?
~/agent/skills/media-server/qb status

# Search via the built-in plugin
~/agent/skills/media-server/qb search "dune part two" movies

# Search and add directly via the TorrentLeech scraper
~/agent/skills/media-server/plugins/torrentleech/search "Dune 2024" --cat movies --add 1 --path $PLEX_MEDIA_PATH/Mike/Movies

# Add a magnet straight to a user's TV folder
~/agent/skills/media-server/qb add "magnet:?xt=urn:btih:..." --tv

# What does Mike already have?
~/agent/skills/media-server/qb ls-plex mike movies

# How much space is left?
~/agent/skills/media-server/qb disk
```

## Troubleshooting

**WebUI returns Forbidden from localhost.** Set `WebUI\LocalHostAuth=false` in qBittorrent settings, then restart:
```bash
sudo systemctl restart qbittorrent-nox@<QB_USER>
```

**`qb search` returns nothing.** Plugin may be installed but flagged `enabled: false`; it still works via the API. Try `qb search <query> --plugin <name>` to call it explicitly, or fall back to the per-plugin `search` script.

**Tracker login fails / cookies expired.** Run the plugin's `search` script with `--relogin`, or delete its cookie file (per plugin README) and retry.

**Search hangs or returns connection errors.** Tracker is probably blocked at the network level. Confirm the proxy is up with `~/agent/skills/vpn/vpn test`, then retry.

## One-time qBittorrent config

Recommended settings on the box:

- `WebUI\LocalHostAuth=false` (no login from localhost)
- `WebUI\AuthSubnetWhitelist=192.168.0.0/24` (or your LAN subnet)
- SOCKS5 proxy configured for all torrent traffic (use a VPN)
- Torrent export dir: `$PLEX_MEDIA_PATH/Torrents`
