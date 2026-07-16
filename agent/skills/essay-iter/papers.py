"""Paper search + PDF fetch helpers for essay-iter.

Backend: **OpenAlex** (https://api.openalex.org). Fully open, no key
required, ~250M works indexed, generous rate limits (~10 req/sec public,
unlimited with email in `User-Agent: vesta/1.0 (mailto:you@example.com)`),
covers metadata, references, citations, similarity.

Fallback for full-text PDFs: **Anna's Archive** (https://annas-archive.org)
mirror of LibGen + Sci-Hub. DOI lookup at `/scidb/<doi>/`. Used only when
OpenAlex's `open_access.oa_url` is missing.

Use cases inside essay-iter:
  * Phase 1 (background reading): search OpenAlex + walk references and
    citations to assemble the corpus.
  * Phase 2 (citation feasibility): for each named source in the outline,
    verify it exists via OpenAlex DOI/title lookup; pull abstract for
    CoVe-style independent verification.
  * Phase 3 (citation reviewer): when an abstract is not enough to verify
    a draft claim, fetch the full PDF (open-access first, Anna's Archive
    second), read the cited section directly. Catches citation inversion.

CLI:
    python papers.py search "filter bubble Pariser critique"
    python papers.py get 10.1145/3366423.3380281
    python papers.py refs 10.1145/3366423.3380281
    python papers.py cited-by 10.1145/3366423.3380281
    python papers.py similar 10.1145/3366423.3380281
    python papers.py pdf 10.1145/3366423.3380281 --out paper.pdf

Env:
  OPENALEX_EMAIL          mailto for the polite pool (default: built-in)
  PAPERS_CACHE_DIR        defaults to ~/.papers_cache
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

OPENALEX_BASE = "https://api.openalex.org"
ANNAS_BASE = "https://annas-archive.org"
DEFAULT_TIMEOUT = (5.0, 30.0)
USER_AGENT = f"vesta/1.0 (mailto:{os.environ.get('OPENALEX_EMAIL', 'you@example.com')})"
CACHE_DIR = Path(os.environ.get("PAPERS_CACHE_DIR", "~/.papers_cache")).expanduser()


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------


def _oa_get(path: str, params: dict | None = None) -> Any:
    """GET against OpenAlex. Retries on transient errors (timeout, connection
    drop, 429, 5xx) only. Lets 4xx client errors propagate immediately so
    bad inputs aren't silently retried."""
    url = f"{OPENALEX_BASE}{path}"
    last_err: str | None = None
    for attempt in range(4):
        try:
            r = requests.get(
                url,
                params=params or {},
                headers={"User-Agent": USER_AGENT},
                timeout=DEFAULT_TIMEOUT,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = repr(e)
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            last_err = f"HTTP {r.status_code}"
            time.sleep(2.0 * (attempt + 1))
            continue
        r.raise_for_status()
    raise RuntimeError(f"OpenAlex retries exhausted for {path}: {last_err}")


def _normalize_id(paper_id: str) -> str:
    """Accept DOI, OpenAlex W-id, arXiv id, or full URL. Return an OpenAlex id."""
    p = paper_id.strip()
    if re.match(r"^W\d+$", p):
        return p  # native OpenAlex id
    if p.startswith("10.") or "/" in p[:6]:
        return f"doi:{p}"
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", p):
        return f"doi:10.48550/arXiv.{p}"
    if p.lower().startswith(("doi:", "arxiv:")):
        return p
    return p


def _slim(work: dict) -> dict:
    """Trim an OpenAlex work record to the fields the agent actually needs."""
    if not work:
        return {}
    auth = [(a or {}).get("author", {}).get("display_name") for a in work.get("authorships") or []]
    src = (work.get("primary_location") or {}).get("source") or {}
    topic = work.get("primary_topic") or {}
    return {
        "id": work.get("id"),  # OpenAlex W-id URL, e.g. https://openalex.org/W123
        "doi": work.get("doi"),
        "title": work.get("title"),
        "authors": [a for a in auth if a],
        "year": work.get("publication_year"),
        "venue": src.get("display_name"),
        "abstract": _abstract_from_inverted(work.get("abstract_inverted_index")),
        "citation_count": work.get("cited_by_count"),
        "reference_count": len(work.get("referenced_works") or []),
        "open_access_url": (work.get("open_access") or {}).get("oa_url"),
        "primary_topic": topic.get("display_name") if topic else None,
    }


def _abstract_from_inverted(inv: dict | None) -> str | None:
    """OpenAlex stores abstracts as a position-inverted index. Reconstruct."""
    if not inv:
        return None
    flat: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            flat[p] = word
    if not flat:
        return None
    return " ".join(flat[i] for i in sorted(flat) if i in flat)


def search(query: str, *, limit: int = 10, year_from: int | None = None) -> list[dict]:
    params: dict = {"search": query, "per_page": min(limit, 100)}
    if year_from is not None:
        params["filter"] = f"publication_year:>{year_from - 1}"
    data = _oa_get("/works", params=params)
    return [_slim(w) for w in data.get("results", [])][:limit]


def get_paper(paper_id: str) -> dict:
    pid = _normalize_id(paper_id)
    return _slim(_oa_get(f"/works/{pid}"))


def references(paper_id: str, *, limit: int = 50) -> list[dict]:
    """The works this paper cites. OpenAlex exposes this as referenced_works
    on the source record (a list of W-ids); we look each up in a single
    /works?filter=ids.openalex:... query for speed."""
    pid = _normalize_id(paper_id)
    src = _oa_get(f"/works/{pid}", params={"select": "referenced_works"})
    ids = (src.get("referenced_works") or [])[:limit]
    if not ids:
        return []
    # OpenAlex caps the ids filter at ~50 per request; chunk if needed.
    out: list[dict] = []
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        # filter expects bare W-ids without the /works/ prefix
        ids_str = "|".join(w.rsplit("/", 1)[-1] for w in chunk)
        data = _oa_get("/works", params={"filter": f"ids.openalex:{ids_str}", "per_page": 50})
        out.extend(_slim(w) for w in data.get("results", []))
    return out


def cited_by(paper_id: str, *, limit: int = 50) -> list[dict]:
    """Papers citing `paper_id`. Forward citation walk."""
    pid = _normalize_id(paper_id)
    bare_id = pid.rsplit("/", 1)[-1] if pid.startswith("W") else pid
    # OpenAlex cites filter expects the OpenAlex W-id; resolve first if DOI.
    if not bare_id.startswith("W"):
        src = _oa_get(f"/works/{pid}", params={"select": "id"})
        bare_id = (src.get("id") or "").rsplit("/", 1)[-1]
        if not bare_id:
            return []
    data = _oa_get("/works", params={"filter": f"cites:{bare_id}", "per_page": min(limit, 100)})
    return [_slim(w) for w in data.get("results", [])][:limit]


def similar(paper_id: str, *, limit: int = 10) -> list[dict]:
    """Papers related to `paper_id` by OpenAlex's `related_works` field
    (concept-graph similarity, not pure embedding NN)."""
    pid = _normalize_id(paper_id)
    src = _oa_get(f"/works/{pid}", params={"select": "related_works"})
    ids = (src.get("related_works") or [])[:limit]
    if not ids:
        return []
    ids_str = "|".join(w.rsplit("/", 1)[-1] for w in ids)
    data = _oa_get("/works", params={"filter": f"ids.openalex:{ids_str}", "per_page": min(limit, 100)})
    return [_slim(w) for w in data.get("results", [])][:limit]


# ---------------------------------------------------------------------------
# PDF fetching
# ---------------------------------------------------------------------------


def _slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:80]
    return s.strip("_") or "paper"


def fetch_pdf(
    paper_id_or_doi: str,
    *,
    out_dir: Path | None = None,
    prefer: tuple[str, ...] = ("openaccess", "annas"),
) -> Path:
    """Best-effort PDF fetch. `prefer` controls source order:
    'openaccess' -> OpenAlex's open_access.oa_url
    'annas'      -> Anna's Archive scidb (requires DOI)
    """
    out_dir = out_dir or (CACHE_DIR / "pdfs")
    out_dir.mkdir(parents=True, exist_ok=True)
    paper = get_paper(paper_id_or_doi)
    title = paper.get("title", "untitled") or "untitled"
    doi = (paper.get("doi") or "").replace("https://doi.org/", "")
    out = out_dir / f"{_slugify(title)}.pdf"
    last_err: Exception | None = None
    for source in prefer:
        try:
            if source == "openaccess":
                url = paper.get("open_access_url")
                if not url:
                    continue
                _download(url, out)
                return out
            if source == "annas":
                if not doi:
                    continue
                pdf_url = _annas_resolve_pdf(f"{ANNAS_BASE}/scidb/{doi}/")
                if not pdf_url:
                    continue
                _download(pdf_url, out)
                return out
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"could not fetch PDF for {paper_id_or_doi!r} (DOI={doi!r}); last error: {last_err}")


def _download(url: str, out: Path) -> None:
    r = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
        stream=True,
    )
    r.raise_for_status()
    with out.open("wb") as f:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)


def _annas_resolve_pdf(scidb_url: str) -> str | None:
    """Scrape Anna's Archive scidb page for the first http(s) PDF link."""
    r = requests.get(
        scidb_url,
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
        allow_redirects=True,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    html = r.text
    for pat in (
        r'href="(https?://[^"]+?\.pdf)"',
        r'href="(https?://[^"]+?ipfs[^"]+?)"',
    ):
        m = re.findall(pat, html, flags=re.I)
        if m:
            return m[0]
    return None


def search_annas(query: str, content: str = "magazine", limit: int = 5) -> list[dict]:
    """Free-text search Anna's Archive (books, magazines, journal articles)."""
    r = requests.get(
        f"{ANNAS_BASE}/search",
        params={"q": query, "content": content},
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    md5s = re.findall(r'href="/md5/([a-f0-9]{32})"', r.text)
    seen: set[str] = set()
    out: list[dict] = []
    for md5 in md5s:
        if md5 in seen:
            continue
        seen.add(md5)
        out.append({"md5": md5, "link": f"{ANNAS_BASE}/md5/{md5}"})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="papers", description=(__doc__ or "").split("\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="Free-text search OpenAlex.")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--year-from", type=int, default=None)

    gp = sub.add_parser("get", help="Get one paper by DOI / arXiv id / OpenAlex W-id.")
    gp.add_argument("id")

    rp = sub.add_parser("refs", aliases=["references"], help="List papers this one cites.")
    rp.add_argument("id")
    rp.add_argument("--limit", type=int, default=50)

    cp = sub.add_parser("cited-by", help="List papers citing this one.")
    cp.add_argument("id")
    cp.add_argument("--limit", type=int, default=50)

    np = sub.add_parser("similar", help="Concept-similar papers.")
    np.add_argument("id")
    np.add_argument("--limit", type=int, default=10)

    pdfp = sub.add_parser("pdf", help="Download PDF (open-access first, Anna's Archive fallback).")
    pdfp.add_argument("id")
    pdfp.add_argument("--out", type=Path, default=None)

    asp = sub.add_parser("search-annas", help="Search Anna's Archive (books, magazines).")
    asp.add_argument("query")
    asp.add_argument("--content", default="magazine")
    asp.add_argument("--limit", type=int, default=5)

    args = p.parse_args(argv)

    try:
        if args.cmd == "search":
            _print(search(args.query, limit=args.limit, year_from=args.year_from))
        elif args.cmd == "get":
            _print(get_paper(args.id))
        elif args.cmd in ("refs", "references"):
            _print(references(args.id, limit=args.limit))
        elif args.cmd == "cited-by":
            _print(cited_by(args.id, limit=args.limit))
        elif args.cmd == "similar":
            _print(similar(args.id, limit=args.limit))
        elif args.cmd == "pdf":
            path = fetch_pdf(args.id, out_dir=args.out.parent if args.out else None)
            if args.out:
                path = path.rename(args.out)
            print(path)
        elif args.cmd == "search-annas":
            _print(search_annas(args.query, content=args.content, limit=args.limit))
    except Exception as e:
        print(f"papers: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
