---
name: spotify
description: This skill should be used when the user asks about "spotify", "music", "playlist", "playlists", "song", "songs", "track", "tracks", "now playing", "what's playing", "play", "pause", "skip", "queue", or needs to search for music, manage playlists, or control playback.
---

# Spotify — CLI: spotify

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

Keeps the library tidy — ensures all playlist tracks are liked, and sorts orphan liked songs into the right playlists by genre.

```bash
# Like all tracks from own playlists that aren't liked yet
spotify organize sync
spotify organize sync --dry-run

# Sort orphan liked songs into playlists using genre rules
spotify organize sort
spotify organize sort --dry-run

# Run both sync + sort together
spotify organize full
spotify organize full --dry-run

# View current genre rules and skip list
spotify organize config

# Reset config to defaults
spotify organize config --init

# Watch daemon — detect newly liked songs and notify (run in a screen session)
spotify organize watch                   # polls every 60 seconds (default)
spotify organize watch --interval 30     # custom poll interval in seconds
spotify organize watch --init            # initialize state file without processing
```

**How it works:**
1. **sync** — Fetches all playlists owned by the user, collects every track, and likes any that aren't already saved
2. **sort** — Finds liked songs that aren't in any own playlist, looks up artist genres via Spotify API, and matches them to playlists using keyword rules (e.g. "jazz" → Jazz playlist, "rock" → Rock playlist)
3. Songs can go into multiple playlists if their genres match multiple rules
4. **watch** — Runs as a daemon, polling the most recent 20 liked songs every 60 seconds. Detects new likes, fetches genre info, and writes a notification file for the agent to process.

**Watch daemon details:**
- The daemon only DETECTS and NOTIFIES — playlist sorting decisions are left to the agent
- Run `spotify organize watch --init` once first to snapshot your existing liked songs (otherwise the daemon auto-inits on first start)
- After init, only songs liked AFTER the daemon starts will be detected — not the full backlog
- Notification includes: track name, artist, track ID, track URI, and artist genres from Spotify
- Logs progress to stderr — works well in a screen session: `screen -S spotify-watch spotify organize watch`
- State file: `~/.spotify/watch_state.json` — tracks known liked IDs and last poll time
- Notifications written to: `~/vesta/notifications/spotify_liked_{timestamp}.json`

**Config** lives at `~/.spotify/organize.json`:
- `skip_playlists` — playlist names to exclude from auto-sorting (queues, mixtapes, ambiguous ones)
- `genre_rules` — list of `{keywords: [...], playlist: "name"}` mappings (used by `sort` command, NOT by watch daemon)

**Important notes:**
- Only processes playlists owned by the user, not followed playlists
- Always use `--dry-run` first to preview what would change
- The sort step can take a few minutes for large libraries (artist genre lookups)
- Unmatched tracks stay as liked-only — review them manually and consider creating new playlists
- After creating new playlists, run `spotify organize config --init` to refresh defaults, or edit `~/.spotify/organize.json` directly to add new genre rules

### Playlists
```bash
# List all playlists
spotify playlists list

# Show playlist tracks
spotify playlists show --id <PLAYLIST_ID>

# Create playlist
spotify playlists create --name "My Playlist" --description "desc"
spotify playlists create --name "Private Vibes" --private

# Add tracks to playlist
spotify playlists add --id <PLAYLIST_ID> --uris "spotify:track:xxx,spotify:track:yyy"

# Remove tracks from playlist
spotify playlists remove --id <PLAYLIST_ID> --uris "spotify:track:xxx"

# View liked songs
spotify playlists liked
spotify playlists liked --limit 20 --offset 100
```

### Search
```bash
# Search tracks (default)
spotify search "bohemian rhapsody"

# Search albums
spotify search "dark side of the moon" --type album

# Search artists
spotify search "radiohead" --type artist

# Multi-type search
spotify search "daft punk" --type "track,album,artist"

# Limit results
spotify search "jazz" --limit 5
```

### Playback (requires Spotify Premium)
```bash
# What's playing now
spotify playback current

# List available devices
spotify playback devices

# Play/resume
spotify playback play
spotify playback play --uri spotify:track:xxx
spotify playback play --context spotify:playlist:xxx
spotify playback play --device <DEVICE_ID>

# Pause
spotify playback pause

# Skip forward/back
spotify playback skip
spotify playback skip --direction previous
spotify playback previous

# Volume
spotify playback volume 75

# Add to queue
spotify playback queue --uri spotify:track:xxx

# Shuffle
spotify playback shuffle on
spotify playback shuffle off

# Repeat
spotify playback repeat off
spotify playback repeat track
spotify playback repeat context

# Transfer to another device
spotify playback transfer --device-id <ID> --play
```

### Auth
```bash
spotify auth status    # Check if authenticated
spotify auth login     # Start OAuth flow
spotify auth setup     # Save app credentials
```

## Playback Gotchas
- **Playlists use `--context`, not `--uri`**: `spotify playback play --context spotify:playlist:xxx`. The `--uri` flag is for individual tracks only. Playlist URIs (especially `playlist_v2` type) fail with `--uri`.
- **Device flag is `--device`**, not `--device-id`: `spotify playback play --device <ID> --context spotify:playlist:xxx`
- **Artist context URIs give 403 premium_required**: `--context 'spotify:artist:...'` fails. For individual songs, always use `--uri 'spotify:track:...'`. For albums/playlists, `--context` works fine.
- **No active device?** Open Spotify on a device first, then retry the play command.

## Notes
- Playback control requires Spotify Premium + at least one Spotify client open
- All output is JSON
- CLI built with spotipy (Python Spotify Web API wrapper)
- Install via: `uv tool install <path-to-skill>/cli`
- Spotify API doesn't expose playlist folders (client-side only feature)
- To delete/unfollow a playlist, use the Spotify API directly via spotipy (no CLI command yet — use `sp.current_user_unfollow_playlist(id)`)
