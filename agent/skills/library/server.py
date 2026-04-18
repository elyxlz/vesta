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


async def serve_text(request: web.Request) -> web.Response:
    filename = _sanitize(request.match_info["filename"])
    if not filename:
        return web.Response(status=400, text="invalid filename")
    path = TEXT_DIR / filename
    if not path.exists():
        return web.Response(status=404, text="book not found")
    return web.Response(
        body=path.read_bytes(),
        content_type="application/json",
        headers=CORS,
    )


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


# --- App ---

app = web.Application()
app.router.add_get("/health", health)
app.router.add_get("/catalog", catalog)
app.router.add_get("/text/{filename}", serve_text)
app.router.add_get("/audio/{filename}", serve_audio)
app.router.add_get("/cover/{filename}", serve_cover)
app.router.add_get("/search", search_text)
app.router.add_get("/search/semantic", search_semantic)

if __name__ == "__main__":
    port = int(os.environ.get("SKILL_PORT", "8100"))
    print(f"[library] serving on port {port}, data_dir={DATA_DIR}", flush=True)
    web.run_app(app, host="0.0.0.0", port=port, print=None)
