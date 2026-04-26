# Plex integration

Plex's expected layout under `MEDIA_LIBRARY_PATH` for this skill:

```
$MEDIA_LIBRARY_PATH/
├── <User1>/
│   ├── Movies/
│   └── TVShows/
├── <User2>/
│   ├── Movies/
│   └── TVShows/
└── Torrents/   (exported .torrent file archive, optional)
```

Per-user Movies/TVShows folders is the convention Plex uses when configured with one library per user. Adapt `<User>` to your actual library names.

## Adding torrents into the right place

The generic `qb add` saves to `$MEDIA_LIBRARY_PATH` by default. For Plex's per-user layout, pass `--path` explicitly:

```bash
~/agent/skills/media-server/qb add "magnet:?xt=..." --path "$MEDIA_LIBRARY_PATH/Mike/Movies"
~/agent/skills/media-server/qb add "magnet:?xt=..." --path "$MEDIA_LIBRARY_PATH/Sarah/TVShows"
```

`plugins/<tracker>/search --add N --path <dir>` also takes a save path; same pattern applies.

## Browsing

```bash
~/agent/skills/media-server/qb ls-library             # top of library: list users
~/agent/skills/media-server/qb ls-library mike        # what Mike has
~/agent/skills/media-server/qb ls-library mike/Movies # Mike's movies
```

## Adding a new media-server backend

Each backend (Plex, Jellyfin, Emby, raw filesystem, etc.) is documented in its own `integrations/<name>/README.md`. The wrapper itself stays generic: it knows about `MEDIA_LIBRARY_PATH` and arbitrary subpaths, nothing more. Backend conventions (per-user dirs, naming schemes, metadata sidecars) live here.

To add Jellyfin: create `integrations/jellyfin/README.md` describing its layout and any conventions, then point users at it.
