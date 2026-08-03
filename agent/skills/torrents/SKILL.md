---
name: torrents
description: This skill should be used when the user asks about their torrent box: searching trackers, adding torrents to qBittorrent, monitoring downloads, or browsing the media library on the server.
---

# Torrents

A home server running qBittorrent on a Linux box, accessed over SSH, with a media library on disk for a downstream player (Plex, Jellyfin, Emby, etc.). Use the `qb` wrapper for download-client and library operations; use `plugins/<tracker>/` for search; see `integrations/<backend>/` for media-server-specific layouts and conventions.

## Quality guidelines

Sensible defaults when downloading:

- **Always ask 1080p or 4K before downloading.** Don't assume; quality preference varies per title and per user.
- **For 4K, target 8GB+ (10GB+ even better).** Smaller "4K" releases are usually re-encoded and lower quality than the size suggests.
- **If 4K isn't available on the tracker**, surface the top-end 1080p options (BluRay 8GB+ or REMUX) and let the user pick. Don't silently fall back to a small 1080p release.

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
~/agent/skills/torrents/qb status                          # Active/incomplete torrents with progress, speed, ETA
~/agent/skills/torrents/qb ls [filter]                     # List all torrents (filter by name/path keyword)
~/agent/skills/torrents/qb add <url> [--path PATH]         # Add by magnet or .torrent URL (default save: MEDIA_LIBRARY_PATH)
~/agent/skills/torrents/qb search <query> [movies|tv|all]  # Search via qBittorrent plugin
~/agent/skills/torrents/qb pause <hash>
~/agent/skills/torrents/qb resume <hash>
~/agent/skills/torrents/qb delete <hash> [--files]         # --files also removes the data
~/agent/skills/torrents/qb info <hash>                     # Properties for a single torrent
~/agent/skills/torrents/qb disk                            # Free space + per-subdir usage on MEDIA_LIBRARY_PATH
~/agent/skills/torrents/qb ls-library [SUBPATH]            # List MEDIA_LIBRARY_PATH (or a subpath of it)
~/agent/skills/torrents/qb find <keyword>                  # Find files in MEDIA_LIBRARY_PATH by name
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

When a per-plugin `search` script downloads a `.torrent` to the server (typically `/tmp/`), upload it directly via the qBittorrent API:

```bash
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST \
  "curl -s -X POST 'http://localhost:$QB_PORT/api/v2/torrents/add' \
   -F 'torrents=@/tmp/movie.torrent' \
   -F 'savepath=$MEDIA_LIBRARY_PATH/<subdir>'"
```

Most plugin `search` scripts do this for you with `--add <n> --path <dir>`.

## Examples

```bash
# Search and add directly via the TorrentLeech scraper
~/agent/skills/torrents/plugins/torrentleech/search "Dune 2024" --cat movies --add 1 --path "$MEDIA_LIBRARY_PATH/Mike/Movies"

# Add a magnet to a specific path
~/agent/skills/torrents/qb add "magnet:?xt=urn:btih:..." --path "$MEDIA_LIBRARY_PATH/Mike/Movies"
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

Recommended settings on the box (see Troubleshooting for `WebUI\LocalHostAuth=false`):

- `WebUI\AuthSubnetWhitelist=192.168.0.0/24` (or your LAN subnet)
- SOCKS5 proxy configured for all torrent traffic (use a VPN)
- Torrent export dir: `$MEDIA_LIBRARY_PATH/Torrents`

## Two CLIs, one service each

`qb` **is** the qBittorrent CLI, improved rather than replaced. It briefly became a separate `qbt`
and that was wrong: the skill already shipped an entry point, and the right move was to fix it, not
to park a rival next to it. (The upstream-pr skill says this in as many words: fold new functionality
into the CLI a skill already ships.)

| tool | owns | never touches |
|---|---|---|
| `qb` | the qBittorrent API | trackers, media library |
| `tl` | TorrentLeech: search + fetch `.torrent` | qBittorrent, media library |
| `plex.py` | the Plex library | torrents |

Pipeline is composition: `tl search` -> `tl get <fid>` -> `qb add <file>`.

**`qb` picks its transport automatically.** With `MEDIA_SERVER_HOST` set it SSHes to the media server
exactly as before; without it, it talks HTTP to `$BOX_HOST:8888`. Every original subcommand name is
kept, so old habits still work. `ls-library` and `find` are inherently filesystem operations and say
so plainly when there is no SSH host, instead of returning empty.

```bash
qb status [name] [--all]      qb ls [filter]        qb info <name>
qb add <magnet|hash|file>...  qb pause/resume <name>
qb delete <name> [--files] --yes
qb limits [name] --ratio 1 --hours 192      # --yes required when no name
qb rule --ratio 1 --hours 192 --yes         # GLOBAL, every torrent
qb health     qb disk     qb search <query> [--1080] [--min-gb N]
qb ls-library [SUBPATH]     qb find <keyword>       # need MEDIA_SERVER_HOST

tl search <query> [--1080|--uhd] [--min-gb N] [--max-gb N]
tl get <fid>... [--out DIR]
```

Env: `BOX_HOST`/`QB_HOST`/`QB_PORT`, `QB_MOVIES`, `QB_TV`, `MEDIA_LIBRARY_PATH`.
TorrentLeech: `~/.torrentleech_cred` (600) + `~/.torrentleech_cookies`, login re-runs only when stale.

**Prefer `tl` for searching.** Same titles: 11 seeders public vs 300+ on TorrentLeech, and throughput
went 3 MB/s -> 83 MB/s on the same film. TL's *website* needs the VPN (direct returns 000, via SOCKS
200); the torrent traffic does not, because the media box reaches the tracker itself.

### Safety properties, each one a bug that actually bit

- **Anything able to act on every torrent at once demands `--yes`.** `qb limits` with no name matched
  every torrent on the box and would have rewritten every share limit silently.
- **Refusals exit 1, never 0**, so a script cannot read a refusal as success.
- **`rule` prints its blast radius first.** It once looked like "65 of 72 would pause" when the true
  answer was 2, because 61 were already paused.
- **The global rule pauses, never deletes** (`max_ratio_act=0`), so a private-tracker torrent can be
  re-seeded rather than re-downloaded.
- **Name matching folds `.`, `_`, `-` and spaces, and accepts multiple words**, so `qb info quiet
  place 2018` works. A plain substring match on "quiet place" matched one of three torrents named
  `A.Quiet.Place...`; a delete that hits a surprising subset is worse than one that errors.

### Two findings worth keeping

- **Listed seeders are a claim, connected peers are the fact.** A release advertising 28 seeders found
  one live peer and crawled at 0.01 MB/s. **Never quote an ETA from a fresh add**: readings of
  33h/108h/300h settled to 40min/115min/150min once peer discovery and cache warmup finished.
- **`qb health` separates disk from network.** Peers connected, zero throughput and
  `write_cache_overload` near 100% is a saturated disk that clears itself; calling it a network fault
  sends you hunting a VPN that was never involved.
- **The filename in TorrentLeech's download URL is arbitrary** (`/download/<fid>/x.torrent` works), and
  searching the tracker for a bare fid does *not* reliably return it, so the lookup was both pointless
  and a source of failures.
