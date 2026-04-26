---
name: media-server
description: This skill should be used when the user asks about their home media server: searching trackers, adding torrents, monitoring downloads, or browsing the media library.
---

# Media Server

A home server running qBittorrent on a Linux box, accessed over SSH, with a media library on disk for a downstream player (Plex, Jellyfin, Emby, etc.). Use the `qb` wrapper for download-client and library operations; use `plugins/<tracker>/` for search; see `integrations/<backend>/` for media-server-specific layouts and conventions.

## Connection

Required env vars:

- `MEDIA_SERVER_HOST`     hostname or IP
- `MEDIA_SERVER_SSH_PORT` SSH port (default: 22)
- `MEDIA_SERVER_USER`     SSH username
- `QB_PORT`               qBittorrent WebUI port (default: 8888)
- `MEDIA_LIBRARY_PATH`    media library base path (default: `/media/library`)

Vesta's SSH key should be pre-installed; no password needed. Tracker traffic must go through a proxy: pull it from the `vpn` skill rather than reading `SOCKS5_*` directly.

## CLI

```bash
~/agent/skills/media-server/qb status                          # Active/incomplete torrents with progress, speed, ETA
~/agent/skills/media-server/qb ls [filter]                     # List all torrents (filter by name/path keyword)
~/agent/skills/media-server/qb add <url> [--path PATH]         # Add by magnet or .torrent URL (default save: MEDIA_LIBRARY_PATH)
~/agent/skills/media-server/qb search <query> [movies|tv|all]  # Search via qBittorrent plugin
~/agent/skills/media-server/qb pause <hash>
~/agent/skills/media-server/qb resume <hash>
~/agent/skills/media-server/qb delete <hash> [--files]         # --files also removes the data
~/agent/skills/media-server/qb info <hash>                     # Properties for a single torrent
~/agent/skills/media-server/qb disk                            # Free space + per-subdir usage on MEDIA_LIBRARY_PATH
~/agent/skills/media-server/qb ls-library [SUBPATH]            # List MEDIA_LIBRARY_PATH (or a subpath of it)
~/agent/skills/media-server/qb find <keyword>                  # Find files in MEDIA_LIBRARY_PATH by name
```

`qb add` accepts URLs (magnets, http(s) `.torrent` URLs) only. For a `.torrent` already on disk, see "Adding a local .torrent" below.

## Integrations

The wrapper is media-server-agnostic: it knows about `MEDIA_LIBRARY_PATH` and arbitrary subpaths, nothing more. Backend-specific conventions (directory layouts, naming, sidecar metadata) live in their own README under `integrations/<backend>/`.

Currently documented:

- **Plex**: `integrations/plex/` (see its [README](integrations/plex/README.md))

To wire up a different backend, create `integrations/<name>/README.md` describing its layout and any conventions, then point users at it.

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
   -F 'savepath=$MEDIA_LIBRARY_PATH/<subdir>'"
```

Most plugin `search` scripts do this for you with `--add <n> --path <dir>`.

## Examples

```bash
# What's downloading right now?
~/agent/skills/media-server/qb status

# Search via the built-in plugin
~/agent/skills/media-server/qb search "dune part two" movies

# Search and add directly via the TorrentLeech scraper
~/agent/skills/media-server/plugins/torrentleech/search "Dune 2024" --cat movies --add 1 --path "$MEDIA_LIBRARY_PATH/Mike/Movies"

# Add a magnet to a specific path
~/agent/skills/media-server/qb add "magnet:?xt=urn:btih:..." --path "$MEDIA_LIBRARY_PATH/Mike/Movies"

# Browse the library
~/agent/skills/media-server/qb ls-library mike/Movies

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
- Torrent export dir: `$MEDIA_LIBRARY_PATH/Torrents`
