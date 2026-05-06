# TorrentLeech plugin

Two ways to search TorrentLeech, both routed through the configured proxy:

1. **Standalone scraper** (preferred): `./search` in this directory. Logs in with cookies, scrapes the site, can add the chosen result straight to qBittorrent in one call. Survives qBittorrent plugin quirks.
2. **qBittorrent plugin**: `torrentleech.py` is a nova3 search engine. Use via `qb search <query> --plugin torrentleech` (uses qBittorrent's own search API). Install once with the curl below.

## Required env vars

- `TL_USERNAME`, `TL_PASSWORD`     TorrentLeech login
- `TL_COOKIE_FILE`                 cookie jar path (default: `~/.tl_cookies`)

For ISP/region bypass (most users will need this), set these in your shell so the script can pick them up:
- `SOCKS5_HOST`, `SOCKS5_PORT`, `SOCKS5_USER`, `SOCKS5_PASS`

Confirm the proxy is up before searching:

```bash
~/agent/skills/vpn/vpn test
~/agent/skills/media-server/plugins/torrentleech/search "Dune 2024" --cat movies
```

(The `search` script auto-detects `SOCKS5_HOST` and routes through it. A future change should make it pull the URL from the `vpn` skill instead of reading the env vars directly.)

## Categories

| Name     | TorrentLeech IDs |
| -------- | ---------------- |
| movies   | 1,8,9,10,11,12,13,14,15,29,36,37,43,47 |
| tv       | 2,26,27,32,44 |
| music    | 16-25 |
| games    | 3,33-35,38-42 |
| software | 4,28,30,31 |
| anime    | 5,6,7 |
| books    | 45,46 |

`./search` accepts `--cat movies|tv|all` or a numeric category ID directly.

## Installing the qBittorrent plugin (one-time)

```bash
QB_PORT=${QB_PORT:-8888}
ssh -p $MEDIA_SERVER_SSH_PORT $MEDIA_SERVER_USER@$MEDIA_SERVER_HOST \
  "curl -s -X POST 'http://localhost:'$QB_PORT'/api/v2/search/installPlugin' \
   -d 'sources=file:///home/'$MEDIA_SERVER_USER'/agent/skills/media-server/plugins/torrentleech/torrentleech.py'"
```

Plugin may show `enabled: false` in the API listing but still works when called by name. Verify with `qb search "test" --plugin torrentleech`.
