"""Library skill server -- serves book catalog, text, audio, and search."""

import json
import os
import pathlib
import sys

from aiohttp import web

DATA_DIR = pathlib.Path.home() / "agent" / "data" / "skills" / "library"
TEXT_DIR = DATA_DIR / "text"
AUDIO_DIR = DATA_DIR / "audio"
COVERS_DIR = DATA_DIR / "covers"
SEARCH_DIR = DATA_DIR / "search"
CATALOG_PATH = DATA_DIR / "catalog.json"

# Add skill's scripts dir to path for importing search module (code lives here, data in ~/agent/data/skills/library/search)
sys.path.insert(0, str(pathlib.Path(__file__).parent / "scripts"))

CORS = {"Access-Control-Allow-Origin": "*"}

AUDIO_CONTENT_TYPES = {
    ".m4b": "audio/mp4",
    ".mp3": "audio/mpeg",
}

COVER_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _sanitize(filename: str) -> str | None:
    if ".." in filename or "/" in filename:
        return None
    return filename


# --- Routes ---


async def health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def catalog(_request: web.Request) -> web.Response:
    if not CATALOG_PATH.exists():
        return web.json_response([], headers=CORS)
    return web.Response(
        body=CATALOG_PATH.read_bytes(),
        content_type="application/json",
        headers=CORS,
    )


_CORPUS_MAP_CACHE: dict[str, str] | None = None


def _corpus_map() -> dict[str, str]:
    """Map catalog filename (*.epub) → corpus filename (*.txt).

    Built from the corpus_index and the catalog. Cached after first load.
    Lets /text fall back to the plain-text corpus when a dedicated
    chapter-by-chapter JSON is not yet extracted for a book.
    """
    global _CORPUS_MAP_CACHE
    if _CORPUS_MAP_CACHE is not None:
        return _CORPUS_MAP_CACHE
    mapping: dict[str, str] = {}
    index_path = SEARCH_DIR / "corpus_index.json"
    if index_path.exists():
        try:
            entries = json.loads(index_path.read_text())
            for entry in entries:
                title = entry.get("title", "")
                mapping[title] = entry["filename"]
        except (OSError, json.JSONDecodeError):
            pass
    if CATALOG_PATH.exists():
        try:
            catalog_data = json.loads(CATALOG_PATH.read_text())
            for book in catalog_data:
                title = book.get("title", "")
                fn = book.get("filename", "")
                if title and title in mapping and fn:
                    mapping[fn] = mapping[title]
        except (OSError, json.JSONDecodeError):
            pass
    _CORPUS_MAP_CACHE = mapping
    return mapping


async def serve_text(request: web.Request) -> web.Response:
    filename = _sanitize(request.match_info["filename"])
    if not filename:
        return web.Response(status=400, text="invalid filename")
    # 1) legacy text/ directory (chapter-by-chapter JSON, if extracted)
    path = TEXT_DIR / filename
    if path.exists():
        return web.Response(body=path.read_bytes(), content_type="application/json", headers=CORS)
    # 2) resolve catalog filename → corpus text and serve as plain text
    corpus_filename = _corpus_map().get(filename, filename)
    corpus_path = SEARCH_DIR / "corpus" / corpus_filename
    if corpus_path.exists():
        return web.Response(
            body=corpus_path.read_bytes(),
            content_type="text/plain",
            charset="utf-8",
            headers=CORS,
        )
    return web.Response(status=404, text="book not found")


async def serve_cover(request: web.Request) -> web.Response:
    filename = _sanitize(request.match_info["filename"])
    if not filename:
        return web.Response(status=400, text="invalid filename")
    path = COVERS_DIR / filename
    if not path.exists():
        return web.Response(status=404, text="cover not found")
    suffix = path.suffix.lower()
    content_type = COVER_CONTENT_TYPES.get(suffix, "application/octet-stream")
    return web.Response(
        body=path.read_bytes(),
        content_type=content_type,
        headers={"Cache-Control": "public, max-age=86400", **CORS},
    )


async def serve_audio(request: web.Request) -> web.Response:
    filename = _sanitize(request.match_info["filename"])
    if not filename:
        return web.Response(status=400, text="invalid filename")
    path = AUDIO_DIR / filename
    if not path.exists():
        return web.Response(status=404, text="audio file not found")
    suffix = path.suffix.lower()
    if suffix not in AUDIO_CONTENT_TYPES:
        return web.Response(status=400, text="unsupported audio format")

    file_size = path.stat().st_size
    content_type = AUDIO_CONTENT_TYPES[suffix]

    # Range requests for seeking
    range_header = request.headers.get("Range")
    if range_header:
        try:
            range_spec = range_header.replace("bytes=", "")
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(length)
            return web.Response(
                body=data,
                status=206,
                content_type=content_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                    **CORS,
                },
            )
        except (ValueError, IndexError):
            return web.Response(status=416, text="invalid range")

    # Full file -- stream to avoid loading into memory
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": content_type,
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            **CORS,
        },
    )
    await response.prepare(request)
    with open(path, "rb") as f:
        while chunk := f.read(256 * 1024):
            await response.write(chunk)
    await response.write_eof()
    return response


async def search_text(request: web.Request) -> web.Response:
    from search import search_books

    q = request.query.get("q", "").strip()
    if not q:
        return web.json_response([], headers=CORS)
    limit = int(request.query.get("limit", "10"))

    # Title/author matches first
    title_matches = []
    if CATALOG_PATH.exists():
        catalog = json.loads(CATALOG_PATH.read_text())
        ql = q.lower()
        for book in catalog:
            title = book.get("title", "")
            author = book.get("author", "")
            if ql in title.lower() or ql in author.lower():
                title_matches.append(
                    {
                        "book": title,
                        "author": author,
                        "chapter": "",
                        "passage": book.get("description", "")[:200] or title,
                        "filename": book.get("filename", ""),
                        "match_type": "title",
                    }
                )

    # Content matches
    results = search_books(q, limit=limit)

    # Deduplicate: don't show content results for books already in title matches
    title_books = {m["book"] for m in title_matches}
    content_results = [r for r in results if r.get("book") not in title_books]

    combined = title_matches[:5] + content_results
    return web.json_response(combined[:limit], headers=CORS)


async def search_semantic(request: web.Request) -> web.Response:
    from search import semantic_search

    q = request.query.get("q", "").strip()
    if not q:
        return web.json_response([], headers=CORS)
    limit = int(request.query.get("limit", "5"))
    results = semantic_search(q, limit=limit)
    return web.json_response(results, headers=CORS)


# --- Selected book state ---
#
# The dashboard library page lets the user pick an "active" book to read. When
# they ask about it in chat, the agent can run a semantic search against the
# book's corpus and POST the matched passage here as `highlight`; the dashboard
# reader polls /selected and scrolls/highlights to that substring. The
# /selected endpoint is sticky across restarts so the UI can resume on the
# last-opened book.

SELECTED_PATH = DATA_DIR / "selected.json"


def _read_selected() -> dict:
    if SELECTED_PATH.exists():
        try:
            return json.loads(SELECTED_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {"filename": None, "position": None, "highlight": None, "updated_at": None}


def _write_selected(data: dict) -> None:
    SELECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELECTED_PATH.write_text(json.dumps(data, indent=2))


async def get_selected(_request: web.Request) -> web.Response:
    return web.json_response(_read_selected(), headers=CORS)


async def set_selected(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        return web.json_response({"error": "invalid json"}, status=400, headers=CORS)
    import datetime as dt
    current = _read_selected()
    # Allowed fields: filename (str|null), position (int|null), highlight (str|null).
    allowed = {"filename", "position", "highlight"}
    for k, v in body.items():
        if k in allowed:
            current[k] = v
    current["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    _write_selected(current)
    return web.json_response(current, headers=CORS)


async def options_handler(_request: web.Request) -> web.Response:
    return web.Response(headers={
        **CORS,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    })


# --- App ---

app = web.Application()
app.router.add_get("/health", health)
app.router.add_get("/catalog", catalog)
app.router.add_get("/text/{filename}", serve_text)
app.router.add_get("/audio/{filename}", serve_audio)
app.router.add_get("/cover/{filename}", serve_cover)
app.router.add_get("/search", search_text)
app.router.add_get("/search/semantic", search_semantic)
app.router.add_get("/selected", get_selected)
app.router.add_post("/selected", set_selected)
app.router.add_route("OPTIONS", "/{tail:.*}", options_handler)

if __name__ == "__main__":
    port = int(os.environ.get("SKILL_PORT", "8100"))
    print(f"[library] serving on port {port}, data_dir={DATA_DIR}", flush=True)
    web.run_app(app, host="0.0.0.0", port=port, print=None)
