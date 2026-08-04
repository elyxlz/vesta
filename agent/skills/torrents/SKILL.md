---
name: torrents
description: This skill should be used when the user asks about their torrent box: searching public trackers or TorrentLeech, adding torrents to qBittorrent, monitoring or share-limiting downloads, or browsing the media library on the server.
---

# Torrents (CLIs: qb, tl)

qBittorrent as the download client, a media library on disk for a downstream player (Plex, Jellyfin, Emby), and optionally a TorrentLeech account. Two commands, one service each: `qb` talks only to qBittorrent, `tl` talks only to TorrentLeech (search and fetch `.torrent` files). The pipeline is composition: `tl search` -> `tl get <fid>` -> `qb add <file>`.

## Setup (one time)

```bash
uv tool install --editable ~/agent/skills/torrents/cli   # puts qb and tl on PATH
```

Environment, in `~/.bashrc`:

- `MEDIA_SERVER_HOST` (+ `MEDIA_SERVER_USER`, `MEDIA_SERVER_SSH_PORT`): set these when qBittorrent runs on a separate media server reached over SSH. Vesta's SSH key must be installed there.
- `QB_HOST` / `QB_PORT` (defaults: `BOX_HOST` : 8888): where the qBittorrent WebUI answers when there is no SSH host.
- `MEDIA_LIBRARY_PATH` (default `/media/library`), `QB_MOVIES`, `QB_TV`: save locations `qb add` uses.

**`qb` picks its transport from that environment**: with `MEDIA_SERVER_HOST` it runs every API call on the media server over SSH (qBittorrent there stays bound to localhost); without it, direct HTTP to `QB_HOST:QB_PORT`. `ls-library` and `find` are filesystem operations on the media server, so they require the SSH transport and say so when it is missing.

For TorrentLeech (`tl`):

- credentials in `~/.torrentleech_cred`, mode 600: `{"username": "...", "password": "..."}`. The cookie jar `~/.torrentleech_cookies` is managed automatically; login re-runs only when the cookie goes stale.
- the `vpn` skill must be active: the TorrentLeech website is unreachable without the proxy (`tl` pulls it from `vpn proxy-url`). The torrent traffic itself needs no proxy; the download client reaches the tracker on its own.

## Commands

```bash
qb status [name] [--all]      qb ls [filter]        qb info <name>
qb add <magnet|hash|file>...  [--path DIR] [--tv]
qb pause <name>               qb resume <name>
qb delete <name> [--files] --yes
qb limits [name] --ratio 1 --hours 192      # --yes required when no name
qb rule --ratio 1 --hours 192 --yes         # GLOBAL, every torrent
qb health     qb disk
qb search <query> [--1080] [--min-gb N]     # public trackers (apibay)
qb ls-library [SUBPATH]     qb find <keyword>       # need MEDIA_SERVER_HOST

tl search <query> [--1080|--uhd] [--min-gb N] [--max-gb N]
tl get <fid>... [--out DIR]
```

Name arguments accept multiple words and fold `.`, `_`, `-` and spaces, so `qb info quiet place 2018` matches `A.Quiet.Place.2018...`; a hash prefix works everywhere a name does.

**Prefer `tl` for searching**: a private tracker holds far more seeders than public results for the same title, and the download saturates the line where public peers crawl. `qb search` covers what public trackers have.

## Quality guidelines

- **Always ask 1080p or 4K before downloading.** Quality preference varies per title and per user.
- **For 4K, target 8GB+ (10GB+ even better).** Smaller "4K" releases are usually re-encodes.
- **If 4K is not on the tracker**, surface the top-end 1080p options (BluRay 8GB+ or REMUX) and let the user pick; never silently fall back to a small release.

## Safety model

- **Anything able to act on every torrent at once demands `--yes`**, and refusals exit 1, never 0, so a script cannot read a refusal as success.
- **`qb rule` prints its blast radius before acting**, counting only live torrents, so the number means what it says.
- **The global rule pauses, never deletes** (`max_ratio_act=0`): on a private tracker a paused torrent can re-seed, a deleted one must be re-downloaded.
- On a private tracker, share limits are a standing obligation: after adding, set them (`qb limits <name> --ratio 1 --hours 192`) rather than leaving seeding unbounded or cutting it off early.

## Reading the numbers

- **Listed seeders are a claim; connected peers are the fact.** A release advertising many seeders can find one live peer. Never quote an ETA from a fresh add: figures settle only after peer discovery and cache warmup, minutes in.
- **`qb health` separates disk from network.** Peers connected, zero throughput, and `write_cache_overload` near 100% is a saturated disk that clears itself; treating it as a network fault sends you hunting a VPN that was never involved.

## Integrations

`qb` is media-server-agnostic: it knows `MEDIA_LIBRARY_PATH` and arbitrary subpaths, nothing more. Backend-specific conventions (directory layouts, naming, sidecar metadata) live under `integrations/<backend>/`:

- **Plex**: `integrations/plex/` (see its [README](integrations/plex/README.md))

To wire up a different backend, create `integrations/<name>/README.md` describing its layout and conventions.

## Troubleshooting

**WebUI returns Forbidden.** Set `WebUI\LocalHostAuth=false` (SSH transport) or whitelist the caller's subnet with `WebUI\AuthSubnetWhitelist` in qBittorrent settings, then restart: `sudo systemctl restart qbittorrent-nox@<QB_USER>`.

**`tl` reports no VPN proxy.** Confirm the proxy with `vpn test`; the TorrentLeech website is blocked without it.

**TorrentLeech login fails.** Delete `~/.torrentleech_cookies` and retry; if it still fails, re-check `~/.torrentleech_cred`.

## One-time qBittorrent config

Recommended settings on the qBittorrent box:

- `WebUI\AuthSubnetWhitelist=192.168.0.0/24` (or your LAN subnet)
- SOCKS5 proxy configured for all torrent traffic (use a VPN)
- Torrent export dir: `$MEDIA_LIBRARY_PATH/Torrents`
