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

## Three CLIs, one service each

`qb` drives qBittorrent by SSH-ing into `$MEDIA_SERVER_HOST`. Where qBittorrent is reachable over
HTTP instead, every server command in it fails, silently and with an empty result. `qbt` and `tl`
talk to each service directly and are kept **separate on purpose**, so neither knows about the other:

| tool | owns | never touches |
|---|---|---|
| `qbt` | the qBittorrent HTTP API | trackers, media server |
| `tl` | TorrentLeech: search + fetch `.torrent` | qBittorrent, media server |

The pipeline is composition: `tl search` -> `tl get <fid>` -> `qbt add <file>`.

```bash
qbt status [name] [--all]            # active torrents; --all includes finished
qbt add <magnet|hash|file>...        # --tv saves to the TV dir instead of Movies
qbt rm <name> [--files] --yes
qbt limits [name] --ratio 1 --hours 192   # --yes required when no name given
qbt rule --ratio 1 --hours 192 --yes      # GLOBAL: every torrent, present and future
qbt health                           # free space, write-cache overload, queued io
qbt search <query>                   # public trackers (apibay)

tl search <query> [--1080|--uhd] [--min-gb N] [--max-gb N]
tl get <fid>... [--out DIR]          # writes <fid>.torrent, then: qbt add
```

Config is all environment: `BOX_HOST` (qBittorrent host, port 8888), `QBT_MOVIES`, `QBT_TV`.
TorrentLeech reads `~/.torrentleech_cred` (`{"username":..., "password":...}`, mode 600) and caches
its session in `~/.torrentleech_cookies`; login is idempotent and re-authenticates only when the
cookie goes stale.

### Safety properties, each one a bug that actually bit

- **Anything able to act on every torrent at once demands `--yes`.** `qbt limits` with no name
  matched all 72 torrents on the box it was written for and would have rewritten every share limit
  without a word. On a private tracker share limits are standing, so that is not cosmetic.
- **Refusals exit 1, never 0**, so a calling script cannot read "I refused" as "I did it".
- **`rule` prints its blast radius before acting**: how many *live* torrents would pause immediately.
  It once looked like "65 of 72" when the true answer was 2, because 61 were already paused.
- **The global rule pauses, never deletes** (`max_ratio_act=0`), so a private-tracker torrent can be
  re-seeded with one click instead of re-downloaded.
- **Name matching folds `.`, `_`, `-` and spaces together.** Release names mix conventions, and a
  plain substring match on "quiet place" matched one of three torrents named `A.Quiet.Place...`.
  A delete that matches a surprising subset is far worse than one that errors.

### Two findings worth keeping

- **A tracker's listed seeder count is a claim; connected peers are the fact.** They disagree often:
  a release advertising 28 seeders found exactly one live peer and crawled at 0.01 MB/s. So **never
  quote an ETA from a fresh add** — sample for ~10 minutes. Fresh adds have read 33h/108h/300h and
  settled to 40min/115min/150min once peer discovery and cache warmup finished.
- **`qbt health` separates disk from network.** Peers connected, zero throughput, and
  `write_cache_overload` near 100% with a large `queued_io_jobs` is a saturated disk, not a
  connectivity problem, and it clears on its own. Diagnosing that as a network fault sends you
  looking for a VPN or a firewall that was never involved.
- **The filename in TorrentLeech's download URL is arbitrary**: `/download/<fid>/x.torrent` returns
  the right file, so no name lookup is needed. Searching the tracker for a bare fid does *not*
  reliably return that torrent, so the lookup was both pointless and a source of failures.
