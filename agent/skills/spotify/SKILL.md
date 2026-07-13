---
name: spotify
description: Spotify: music, playlists, tracks, playback, queue, library management.
---

# Spotify - CLI: spotify

Manage your Spotify account. Playlists, search, playback control, library organization.

## Setup

See [SETUP.md](SETUP.md) for initial configuration instructions.

## Auth

Run once to configure your Spotify app credentials, then log in:

```bash
spotify auth setup --client-id <YOUR_CLIENT_ID> --client-secret <YOUR_CLIENT_SECRET>
spotify auth login
# Visit the URL printed, authorize the app, then copy the redirect URL back:
spotify auth callback --url "<redirect_url>"
```

Check status at any time:
```bash
spotify auth status
```

- Credentials stored at: `~/.spotify/credentials.json`
- Token cache: `~/.spotify/token.json`
- Token auto-refreshes via cached refresh token

## Commands

### Organize (Library Management)

Keeps the library tidy: ensures all playlist tracks are liked, and sorts orphan liked songs into the right playlists by genre.

```bash
# Like all tracks from own playlists that aren't liked yet
spotify organize sync
spotify organize sync --dry-run

# Sort orphan liked songs into playlists using genre rules
spotify organize sort

# Run both sync + sort together
spotify organize full

# View current genre rules and skip list
spotify organize config

# Reset config to defaults
spotify organize config --init

# Watch daemon - detect newly liked songs and notify (run in a screen session)
spotify organize watch                   # polls every 60 seconds (default)
spotify organize watch --interval 30     # custom poll interval in seconds
spotify organize watch --init            # initialize state file without processing
```

- `sort` matches by artist genre keywords (`~/.spotify/organize.json` holds `genre_rules` + `skip_playlists`); only playlists you own are touched. Always `--dry-run` first.
- `watch` only DETECTS newly liked songs and writes a notification to `~/agent/notifications/spotify_liked_{timestamp}.json` (track name, artist, IDs, artist genres); the sorting decision is left to the agent. Run in a screen session; state lives at `~/.spotify/watch_state.json`.

### Playlists
```bash
spotify playlists list

# Show playlist tracks
spotify playlists show --id <PLAYLIST_ID>

spotify playlists create --name "My Playlist" --description "desc"
spotify playlists create --name "Private Vibes" --private

spotify playlists add --id <PLAYLIST_ID> --uris "spotify:track:xxx,spotify:track:yyy"

spotify playlists remove --id <PLAYLIST_ID> --uris "spotify:track:xxx"

# View liked songs
spotify playlists liked
spotify playlists liked --limit 20 --offset 100
```

### Search
```bash
# Search tracks (default)
spotify search "bohemian rhapsody"

spotify search "dark side of the moon" --type album
spotify search "radiohead" --type artist
spotify search "daft punk" --type "track,album,artist"
spotify search "jazz" --limit 5
```

### Playback (requires Spotify Premium)
```bash
spotify playback current

spotify playback devices

# Play/resume
spotify playback play
spotify playback play --uri spotify:track:xxx
spotify playback play --context spotify:playlist:xxx
spotify playback play --device <DEVICE_ID>

spotify playback pause

spotify playback skip
spotify playback skip --direction previous
spotify playback previous

spotify playback volume 75

spotify playback queue --uri spotify:track:xxx

spotify playback shuffle on
spotify playback shuffle off

spotify playback repeat off
spotify playback repeat track
spotify playback repeat context

spotify playback transfer --device-id <ID> --play
```

## Playback Gotchas
- **Playlists use `--context`, not `--uri`**: `spotify playback play --context spotify:playlist:xxx`. The `--uri` flag is for individual tracks only. Playlist URIs (especially `playlist_v2` type) fail with `--uri`.
- **Device flag is `--device`**, not `--device-id`: `spotify playback play --device <ID> --context spotify:playlist:xxx`
- **Artist context URIs give 403 premium_required**: `--context 'spotify:artist:...'` fails. For individual songs, always use `--uri 'spotify:track:...'`. For albums/playlists, `--context` works fine.
- **No active device?** Open Spotify on a device first, then retry the play command.

## Notes
- All output is JSON
- Install via: `uv tool install --editable <path-to-skill>/cli`
- To delete/unfollow a playlist, use the Spotify API directly via spotipy (no CLI command yet, use `sp.current_user_unfollow_playlist(id)`)
