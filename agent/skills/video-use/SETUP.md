# Video-Use Setup

## 1. Install ffmpeg (required) and yt-dlp (optional)

```bash
# Debian / Ubuntu
apt-get update && apt-get install -y ffmpeg
apt-get install -y yt-dlp   # optional, for pulling clips from URLs

# macOS
brew install ffmpeg
brew install yt-dlp         # optional
```

`ffmpeg` is mandatory - every cut, fade, encode, and subtitle burn goes through it. `yt-dlp` is only needed if you want the nested session to fetch clips from YouTube / other sites.

## 2. Clone and sync

```bash
git clone https://github.com/browser-use/video-use ~/Developer/video-use
cd ~/Developer/video-use && uv sync
```

This pulls the project and installs its Python deps into a local `.venv` via `uv`.

## 3. Add your ElevenLabs API key

Open `~/Developer/video-use/.env` in an editor and paste the key:

```
ELEVENLABS_API_KEY=<your-key-here>
```

Grab the key from https://elevenlabs.io/app/settings/api-keys. The `.env` file is read by the nested Claude Code session at runtime.

## 4. Verify

```bash
ffmpeg -version | head -1
ls ~/Developer/video-use/.env
grep -q ELEVENLABS_API_KEY ~/Developer/video-use/.env && echo "key set" || echo "key MISSING"
(cd ~/Developer/video-use && uv run python -c "import sys; print('video-use env OK:', sys.version.split()[0])")
```

All four lines should succeed. If the last command fails, re-run `uv sync` inside `~/Developer/video-use`.

You're ready: `cd` into any directory of clips and run `claude "edit these into a launch video"`.
