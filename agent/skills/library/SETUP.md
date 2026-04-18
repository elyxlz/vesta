# Library Skill Setup

This skill serves a personal ebook and audiobook library via a small HTTP
service. It reads from `~/agent/data/skills/library/` and exposes catalog, text, cover, audio,
and search endpoints.

## 1. Install dependencies

```bash
uv pip install aiohttp beautifulsoup4 lxml sentence-transformers numpy torch
```

- `aiohttp`: HTTP server (`server.py`)
- `beautifulsoup4`, `lxml`: epub HTML parsing (`extract_books.py`, `build_catalog.py`)
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

The dashboard's Library page expects a service named `library` registered with
vestad. The skill's `serve:` command in `SKILL.md` handles registration and
starts the server under `screen`. The dashboard fetches `/catalog`, book text
from `/text/<filename>`, covers from `/cover/<filename>`, and streams audio
from `/audio/<filename>` (with HTTP range support).

If the Library page is not appearing in the dashboard, make sure:

1. The skill is installed and its `serve:` directive has run (registering the
   `/library` service with vestad).
2. `~/agent/data/skills/library/catalog.json` exists and is non-empty.

## 5. Notes on the catalog format

- `cover` is a relative path string like `"covers/My_Book.jpg"`. The server
  serves cover images from `GET /cover/<filename>`.
- `cover_b64` (a data URL embedded in the catalog) is **deprecated**. Older
  catalogs may contain it; `build_catalog.py` will not write it. Covers should
  be fetched via the `/cover/` route instead.
- `audio_file` is a bare filename (e.g. `"My Book.m4b"`) served by
  `GET /audio/<filename>`.
- `audio_only: true` indicates an audiobook with no matching ebook.
