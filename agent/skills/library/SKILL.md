---
name: library
description: personal ebook and audiobook library with search, reading, and audio playback. Use when the user asks about books, reading, their kindle/audible library, or wants to search their book collection.
serve: PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"library"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && SKILL_PORT=$PORT screen -dmS library python3 ~/agent/skills/library/server.py
---

# Library Skill

Personal ebook and audiobook library with full-text search, semantic search, reading, and audio playback.

## Quick Reference

```bash
# Search books by text
curl "http://localhost:$PORT/search?q=artificial+intelligence&limit=5"

# Semantic search
curl "http://localhost:$PORT/search/semantic?q=meaning+of+life&limit=5"

# Get catalog
curl "http://localhost:$PORT/catalog"

# Get book text
curl "http://localhost:$PORT/text/My_Book.json"

# Get cover image
curl "http://localhost:$PORT/cover/My_Book.jpg"

# Stream audiobook
curl "http://localhost:$PORT/audio/My_Book.m4b"

# Import new epubs
python scripts/extract_books.py        # extract text from epubs
python scripts/build_catalog.py        # rebuild catalog.json
python scripts/build_index.py          # rebuild search embeddings
```

## How It Works

The library skill serves a personal book collection via HTTP. It provides:

- **Catalog**: JSON listing of all books with metadata (title, author, subjects, cover path)
- **Book text**: Extracted chapter-by-chapter JSON for in-app reading
- **Covers**: Cover images served from `/cover/<filename>` (extracted from epubs to `~/agent/data/skills/library/covers/`)
- **Audio**: Audiobook files (m4b/mp3) served with HTTP range request support for seeking
- **Full-text search**: Regex-capable search across all book text
- **Semantic search**: Embedding-based similarity search using sentence-transformers

See `SETUP.md` for install and bootstrap instructions.

## Data Directory

All data is stored in `~/agent/data/skills/library/`:

```
~/agent/data/skills/library/
├── books/          # Source epub files
├── covers/         # Extracted cover thumbnails
├── text/           # Extracted book text JSON (chapter-by-chapter)
├── search/         # Search corpus, index, and embeddings
│   ├── corpus/     # Plain text corpus files
│   ├── corpus_index.json
│   └── embeddings/ # Semantic search embeddings
├── audio/          # Audiobook files (m4b, mp3)
└── catalog.json    # Master catalog with metadata
```

## Dashboard Integration

The Library page is registered in the dashboard config, providing a browsable UI for the book collection with reading and audio playback.

## Import Workflow

1. Place `.epub` files in `~/agent/data/skills/library/books/`
2. Run `python scripts/extract_books.py` to extract chapter text to `~/agent/data/skills/library/text/`
3. Run `python scripts/build_catalog.py` to rebuild `~/agent/data/skills/library/catalog.json` with metadata and covers
4. (Optional) Run `python scripts/build_index.py` to rebuild semantic search embeddings
5. Place audiobook files (`.m4b`, `.mp3`) in `~/agent/data/skills/library/audio/` — matched to books by filename
