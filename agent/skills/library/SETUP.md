# Library Skill Setup

This skill serves a personal ebook and audiobook library via a small HTTP
service. It reads from `~/agent/data/skills/library/` and exposes catalog, text, cover, audio,
and search endpoints.

## 1. Install dependencies

```bash
uv pip install aiohttp beautifulsoup4 lxml pillow sentence-transformers numpy torch
```

- `aiohttp`: HTTP server (`server.py`)
- `beautifulsoup4`, `lxml`: epub HTML parsing (`extract_books.py`, `build_catalog.py`)
- `pillow`: thumbnail generation for the catalog's inline `cover_b64` field (`build_catalog.py`). If absent, the build still succeeds but the catalog ships without thumbnails.
- `sentence-transformers`, `numpy`, `torch`: semantic search (`build_index.py`, `search.py`)

Optional, only required if you use `transcribe.py` to transcribe audiobooks:

- `ffmpeg` / `ffprobe` (CLI): chapter extraction + wav conversion
- A running `whisper-server` listening on `/tmp/whisper-server.sock`

`build_catalog.py` also shells out to `ffprobe` to pull narrator and duration
from audio files; it degrades gracefully if `ffprobe` is missing.

## 2. Bootstrap `~/agent/data/skills/library/`

```bash
mkdir -p ~/agent/data/skills/library/{books,audio,covers,text,search/corpus,search/embeddings}
```

Drop your source files in:

- `~/agent/data/skills/library/books/`: `.epub` files
- `~/agent/data/skills/library/audio/`: `.m4b` / `.mp3` audiobook files

## 3. Import workflow

```bash
cd ~/agent/skills/library

# Extract chapter text to ~/agent/data/skills/library/text/<book>.json
python scripts/extract_books.py

# Rebuild ~/agent/data/skills/library/catalog.json (metadata + covers, matches audio by filename)
python scripts/build_catalog.py

# (Optional) Build semantic search embeddings
python scripts/build_index.py
```

`build_catalog.py` is idempotent: re-running updates existing entries and
appends new ones. Audio-only books (no matching epub) get an entry with
`"audio_only": true`.

## 4. Dashboard integration

The skill ships a ready-made library page for the `dashboard` skill, at
`~/agent/skills/library/dashboard/library.tsx`. It renders a browsable grid
with cover thumbnails, an author/subject filter popover, sort toggles, a
click-through reader with scroll/highlight support, and a lightweight audio
player.

To wire it up:

1. Copy the page into your dashboard's `pages/` directory:

   ```bash
   cp ~/agent/skills/library/dashboard/library.tsx \
     ~/agent/skills/dashboard/app/src/pages/library.tsx
   ```

2. Register it in `~/agent/skills/dashboard/app/src/config.tsx` as a sidebar
   nav item. See the dashboard skill's `SKILL.md` for the config shape.

3. Make sure the `library` service is registered with vestad: the skill's
   `serve:` directive in `SKILL.md` handles this automatically. The page uses
   `apiFetch("library/catalog")` etc. which routes through the dashboard's
   authenticated proxy.

If the page is not appearing, check:

1. The skill is installed and its `serve:` directive has run.
2. `~/agent/data/skills/library/catalog.json` exists and is non-empty.
3. The nav entry is present in your dashboard `config.tsx`.

## 5. Notes on the catalog format

- `cover` is a relative path string like `"covers/My_Book.jpg"`. The server
  serves cover images from `GET /cover/<filename>`.
- `cover_b64` is a base64 data URL embedded in each catalog entry, a resized
  (200px wide) JPEG of the cover. Regenerated from disk on every build by
  `build_catalog.py` (requires Pillow). Lets the dashboard grid render all
  thumbnails from a single authenticated `/catalog` fetch instead of firing
  per-cover requests; native `<img>` tags can't attach bearer auth.
- `audio_file` is a bare filename (e.g. `"My Book.m4b"`) served by
  `GET /audio/<filename>`.
- `audio_only: true` indicates an audiobook with no matching ebook.
