#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["plexapi==4.18.0"]
# ///
"""
plex: CLI for querying a Plex Media Server (library, search, files).

Config (first found wins):
  1. env PLEX_URL + PLEX_TOKEN
  2. ~/.plex/config.json  ->  {"url": "...", "token": "..."}

Commands:
  sections                       list libraries (name, type, item count)
  search <query> [--type T]      search the library; shows year, resolution, size, file path
  has <query> [--type T]         quick check: is <query> in the library? (exit 0 = yes, 1 = no)
  recent [--count N] [--section S]   recently added
  info <title> [--section S]     full details for one item (files, resolution, codec, size, path)

  --json on any command for raw JSON.

Derived from plexapi; owned in-house.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from xml.etree.ElementTree import ParseError

from plexapi.exceptions import PlexApiException
from plexapi.server import PlexServer
from requests import RequestException


def _load_config():
    url = os.environ.get("PLEX_URL", "").strip()
    token = os.environ.get("PLEX_TOKEN", "").strip()
    if url and token:
        return url, token
    cfg = Path.home() / ".plex" / "config.json"
    if cfg.exists():
        try:
            d = json.loads(cfg.read_text())
            return d.get("url", "").strip(), d.get("token", "").strip()
        except (AttributeError, json.JSONDecodeError, OSError, TypeError):
            return url, token
    return url, token


def connect():
    url, token = _load_config()
    if not url or not token:
        sys.exit("error: PLEX_URL + PLEX_TOKEN not set (env or ~/.plex/config.json).\nsee SETUP.md to get a token.")
    try:
        return PlexServer(url, token, timeout=15)
    except (ParseError, PlexApiException, RequestException) as exc:
        sys.exit(f"error: could not connect to plex at {url}: {exc}")


def _gb(n):
    if not isinstance(n, (int, float)):
        return "?"
    return f"{n / 1e9:.1f}GB"


def _resolution(item):
    try:
        return item.media[0].videoResolution or "?"
    except (AttributeError, IndexError, TypeError):
        return "?"


def _files(item):
    out = []
    try:
        for m in item.media:
            out.extend({"file": p.file, "size": getattr(p, "size", 0)} for p in m.parts)
    except (AttributeError, TypeError):
        return []
    return out


def _type_to_libtype(t):
    if not t:
        return None
    t = t.lower()
    return {
        "movie": "movie",
        "movies": "movie",
        "show": "show",
        "shows": "show",
        "tv": "show",
        "episode": "episode",
        "artist": "artist",
        "music": "artist",
    }.get(t, t)


def cmd_sections(plex, args):
    secs = plex.library.sections()
    rows = [{"name": s.title, "type": s.type, "count": s.totalSize} for s in secs]
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    for r in rows:
        print(f"  {r['name']:<20} {r['type']:<8} {r['count']} items")


def _search(plex, query, libtype):
    results = []
    try:
        results = plex.library.search(title=query, libtype=libtype) if libtype else plex.library.search(title=query)
    except (PlexApiException, RequestException):
        # fall back to per-section search
        for s in plex.library.sections():
            try:
                results.extend(s.search(title=query))
            except (PlexApiException, RequestException) as exc:
                print(f"warning: could not search Plex section {s.title}: {exc}", file=sys.stderr)
    return results


def _item_row(it):
    files = _files(it)
    total = sum(f["size"] for f in files)
    return {
        "title": getattr(it, "title", "?"),
        "year": getattr(it, "year", None),
        "type": getattr(it, "type", "?"),
        "resolution": _resolution(it),
        "size": total,
        "files": [f["file"] for f in files],
    }


def cmd_search(plex, args):
    lt = _type_to_libtype(args.type)
    res = _search(plex, args.query, lt)
    rows = [_item_row(it) for it in res]
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print(f"  no matches for '{args.query}'")
        return
    for r in rows:
        yr = f"({r['year']})" if r["year"] else ""
        print(f"  {r['title']} {yr}  [{r['type']}]  {r['resolution']}  {_gb(r['size'])}")
        for f in r["files"]:
            print(f"      {f}")


def cmd_has(plex, args):
    lt = _type_to_libtype(args.type)
    res = _search(plex, args.query, lt)
    # tighten: title contains query (case-insensitive)
    q = args.query.lower()
    hits = [it for it in res if q in getattr(it, "title", "").lower()]
    if args.json:
        print(json.dumps({"query": args.query, "found": bool(hits), "matches": [_item_row(it) for it in hits]}, indent=2))
    elif hits:
        for it in hits:
            r = _item_row(it)
            yr = f"({r['year']})" if r["year"] else ""
            print(f"  YES: {r['title']} {yr}  {r['resolution']}  {_gb(r['size'])}")
    else:
        print(f"  NO: '{args.query}' not in library")
    sys.exit(0 if hits else 1)


def cmd_recent(plex, args):
    if args.section:
        sec = plex.library.section(args.section)
        items = sec.recentlyAdded(maxresults=args.count)
    else:
        items = plex.library.recentlyAdded()[: args.count]
    rows = [_item_row(it) for it in items]
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    for r in rows:
        yr = f"({r['year']})" if r["year"] else ""
        print(f"  {r['title']} {yr}  [{r['type']}]  {r['resolution']}  {_gb(r['size'])}")


def cmd_info(plex, args):
    res = plex.library.section(args.section).search(title=args.title) if args.section else _search(plex, args.title, None)
    q = args.title.lower()
    hits = [it for it in res if q in getattr(it, "title", "").lower()]
    if not hits:
        sys.exit(f"  no match for '{args.title}'")
    it = hits[0]
    detail = {
        "title": getattr(it, "title", "?"),
        "year": getattr(it, "year", None),
        "type": getattr(it, "type", "?"),
        "resolution": _resolution(it),
        "duration_min": round(getattr(it, "duration", 0) / 60000) if getattr(it, "duration", 0) else None,
        "summary": getattr(it, "summary", "")[:300],
        "files": _files(it),
    }
    try:
        detail["codec"] = it.media[0].videoCodec
        detail["container"] = it.media[0].container
    except (AttributeError, IndexError, TypeError):
        detail["codec"] = None
        detail["container"] = None
    if args.json:
        print(json.dumps(detail, indent=2))
        return
    yr = f"({detail['year']})" if detail["year"] else ""
    print(f"  {detail['title']} {yr}  [{detail['type']}]")
    print(f"  resolution: {detail['resolution']}  codec: {detail.get('codec', '?')}  container: {detail.get('container', '?')}")
    if detail["duration_min"]:
        print(f"  duration: {detail['duration_min']} min")
    for f in detail["files"]:
        print(f"  file: {f['file']}  ({_gb(f['size'])})")


def main():
    p = argparse.ArgumentParser(prog="plex", description="Query a Plex Media Server.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sections = sub.add_parser("sections", help="list libraries")
    sections.add_argument("--json", action="store_true", help="raw JSON output")

    sp = sub.add_parser("search", help="search the library")
    sp.add_argument("query")
    sp.add_argument("--type", help="movie|show|episode|artist")
    sp.add_argument("--json", action="store_true", help="raw JSON output")

    hp = sub.add_parser("has", help="is <query> in the library? (exit 0=yes)")
    hp.add_argument("query")
    hp.add_argument("--type", help="movie|show|episode|artist")
    hp.add_argument("--json", action="store_true", help="raw JSON output")

    rp = sub.add_parser("recent", help="recently added")
    rp.add_argument("--count", type=int, default=25)
    rp.add_argument("--section")
    rp.add_argument("--json", action="store_true", help="raw JSON output")

    ip = sub.add_parser("info", help="full details for one item")
    ip.add_argument("title")
    ip.add_argument("--section")
    ip.add_argument("--json", action="store_true", help="raw JSON output")

    args = p.parse_args()
    plex = connect()
    {
        "sections": cmd_sections,
        "search": cmd_search,
        "has": cmd_has,
        "recent": cmd_recent,
        "info": cmd_info,
    }[args.cmd](plex, args)


if __name__ == "__main__":
    main()
