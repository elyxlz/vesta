# Spotify Skill Setup

## Prerequisites

- Python 3.11+
- uv (https://docs.astral.sh/uv/)
- A Spotify account (Premium required for playback control)
- A Spotify Developer app (free)

## Step 1: Create a Spotify App

1. Go to https://developer.spotify.com/dashboard
2. Click "Create app"
3. Fill in a name and description (any values work)
4. Set the Redirect URI to: `https://example.com`
   (This is used for the OAuth flow — you will manually copy the redirect URL)
5. Note your **Client ID** and **Client Secret**

## Step 2: Install the CLI

```bash
uv tool install <path-to-this-skill>/cli
```

## Step 3: Configure credentials

```bash
spotify auth setup --client-id <YOUR_CLIENT_ID> --client-secret <YOUR_CLIENT_SECRET>
```

This saves your credentials to `~/.spotify/credentials.json` (mode 600).

## Step 4: Log in

```bash
spotify auth login
```

This prints an authorization URL. Open it in your browser, authorize the app, and you will be redirected to `https://example.com/?code=...`. Copy the full redirect URL and run:

```bash
spotify auth callback --url "https://example.com/?code=AQ..."
```

## Step 5: Verify

```bash
spotify auth status
```

You should see your Spotify username and `"status": "authenticated"`.

## Optional: Library Organization Config

To initialize the default genre-sorting config:

```bash
spotify organize config --init
```

Edit `~/.spotify/organize.json` to customize:
- `skip_playlists` — playlists to exclude from auto-sorting
- `genre_rules` — keyword → playlist name mappings for genre-based sorting

## Step 6: Add to restart.md

If using the watch daemon, add to `~/vesta/prompts/restart.md`:
```
screen -dmS spotify-watch spotify organize watch
```
