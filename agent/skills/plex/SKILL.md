---
name: plex
description: Query the household Plex Media Server — list libraries, search for a title, check whether the library already has a movie/show, see recently added, and get a file's path/resolution/size. Use when asked "do we have X on plex", "what's in the library", "is X downloaded", or to verify a download landed. Read-only.
---

# Plex

CLI for the household Plex Media Server. Read-only: it reads the library, it does not add, edit, or delete anything.

This is the reliable way to answer "do we already have this?" — it reads Plex's own catalogue, which reflects what's actually on disk and playable, including files added outside the torrent client.

## Setup

Needs `PLEX_URL` + `PLEX_TOKEN`. See [SETUP.md](SETUP.md). Config is read from env first, then `~/.plex/config.json`.

## Usage

```bash
cd ~/agent/skills/plex

./plex.py sections                      # list libraries (name, type, item count)
./plex.py search "the social network"   # search; shows year, resolution, size, file path
./plex.py search "dune" --type movie    # restrict to a type (movie|show|episode|artist)
./plex.py has "moneyball"               # quick check: in the library? exit 0 = yes, 1 = no
./plex.py recent --count 20             # recently added
./plex.py recent --section "Movies"
./plex.py info "steve jobs"             # full details: files, resolution, codec, container, size

# add --json to any command for machine-readable output
./plex.py has "molly's game" --json
```

## Notes

- `has` is the fast "do we own this" check and sets its exit code (0 found / 1 not), so it scripts cleanly before deciding to download.
- `search`/`info` print the real file path on the Plex disk (e.g. `/media/Movies/...`), useful for verifying a download landed in the right folder and matching quality (2160p vs 1080p).
- Apostrophes in a query are fine here (unlike the torrent search); quote the whole query.
- Derived from plexapi, owned in-house. No external repo dependency.
