"""Exa AI CLI — lightweight wrapper around https://api.exa.ai.

Commands:
  exa auth setup --api-key <key>   # save key to ~/.exa/config.json
  exa auth status                  # show where the key is loaded from
  exa search <query> [flags]       # semantic/keyword search
  exa answer <question> [flags]    # Q&A with citations
  exa similar <url> [flags]        # find similar pages
  exa contents <url> [<url>...]    # fetch text/highlights/summary of URLs
  exa research <topic> [flags]     # kick off deep research (async)
  exa research status <id>         # poll a research task
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx


API_BASE = "https://api.exa.ai"
CONFIG_DIR = Path.home() / ".exa"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_TIMEOUT = 60.0
RESEARCH_TIMEOUT = 30.0
RESEARCH_POLL_INTERVAL = 5.0
RESEARCH_MAX_WAIT = 600.0  # 10 min


# --------------------------------------------------------------------------- #
# Auth / config
# --------------------------------------------------------------------------- #


def _load_key_from_file() -> str | None:
    if not CONFIG_FILE.exists():
        return None
    try:
        data = json.loads(CONFIG_FILE.read_text())
        key = data.get("api_key")
        return key if isinstance(key, str) and key else None
    except (json.JSONDecodeError, OSError):
        return None


def _load_key_from_keeper() -> str | None:
    """Try to fetch 'Exa API' record from keeper, if the keeper CLI exists."""
    try:
        result = subprocess.run(
            ["keeper", "get", "Exa API", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        # keeper records typically expose custom fields
        for field in data.get("custom_fields", []) or []:
            if field.get("label", "").lower() in ("api_key", "api key", "key"):
                val = field.get("value")
                if isinstance(val, str) and val:
                    return val
        # some keeper skills return a flat dict
        if isinstance(data.get("api_key"), str):
            return data["api_key"]
        if isinstance(data.get("password"), str):
            return data["password"]
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return None
    return None


def get_api_key() -> str:
    key = os.environ.get("EXA_API_KEY")
    if key:
        return key
    key = _load_key_from_file()
    if key:
        return key
    key = _load_key_from_keeper()
    if key:
        return key
    print(
        "Error: EXA_API_KEY not set. Run `exa auth setup --api-key <key>` or export EXA_API_KEY.",
        file=sys.stderr,
    )
    sys.exit(1)


def auth_setup(api_key: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"api_key": api_key}, indent=2))
    CONFIG_FILE.chmod(0o600)
    print(json.dumps({"status": "ok", "config_file": str(CONFIG_FILE)}, indent=2))


def auth_status() -> None:
    source = None
    key: str | None = None
    if os.environ.get("EXA_API_KEY"):
        source = "env:EXA_API_KEY"
        key = os.environ["EXA_API_KEY"]
    elif _load_key_from_file():
        source = f"file:{CONFIG_FILE}"
        key = _load_key_from_file()
    elif _load_key_from_keeper():
        source = "keeper:Exa API"
        key = _load_key_from_keeper()

    if not key:
        print(
            json.dumps(
                {
                    "status": "unauthenticated",
                    "hint": "run `exa auth setup --api-key <key>`",
                },
                indent=2,
            )
        )
        sys.exit(1)

    masked = key[:6] + "..." + key[-4:] if len(key) > 12 else "***"
    print(json.dumps({"status": "authenticated", "source": source, "key": masked}, indent=2))


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def _headers() -> dict[str, str]:
    return {
        "x-api-key": get_api_key(),
        "Content-Type": "application/json",
    }


def _post(path: str, body: dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    try:
        r = httpx.post(url, headers=_headers(), json=body, timeout=timeout)
    except httpx.HTTPError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        sys.exit(1)
    if r.status_code >= 400:
        print(f"Error {r.status_code}: {r.text}", file=sys.stderr)
        sys.exit(1)
    return r.json()


def _get(path: str, params: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    try:
        r = httpx.get(url, headers=_headers(), params=params or {}, timeout=timeout)
    except httpx.HTTPError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        sys.exit(1)
    if r.status_code >= 400:
        print(f"Error {r.status_code}: {r.text}", file=sys.stderr)
        sys.exit(1)
    return r.json()


# --------------------------------------------------------------------------- #
# Shared builders
# --------------------------------------------------------------------------- #


def _build_contents(args: argparse.Namespace) -> dict[str, Any] | None:
    """Build a `contents` dict from common flags. Returns None if no content flags set."""
    contents: dict[str, Any] = {}
    if getattr(args, "text", False):
        if getattr(args, "max_chars", None):
            contents["text"] = {"maxCharacters": args.max_chars}
        else:
            contents["text"] = True
    if getattr(args, "highlights", False):
        contents["highlights"] = True
    if getattr(args, "summary", None) is not None:
        summary = getattr(args, "summary")
        if summary == "" or summary is True:
            contents["summary"] = True
        else:
            contents["summary"] = {"query": summary}
    return contents or None


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_search(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {"query": args.query, "numResults": args.num}
    if args.type and args.type != "auto":
        body["type"] = args.type
    if args.category:
        body["category"] = args.category
    if args.include_domain:
        body["includeDomains"] = args.include_domain
    if args.exclude_domain:
        body["excludeDomains"] = args.exclude_domain
    if args.start_published:
        body["startPublishedDate"] = args.start_published
    if args.end_published:
        body["endPublishedDate"] = args.end_published
    contents = _build_contents(args)
    if contents:
        body["contents"] = contents
    data = _post("/search", body)
    print(json.dumps(data, indent=2))


def cmd_answer(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {"query": args.question}
    if args.text:
        body["text"] = True
    data = _post("/answer", body)
    print(json.dumps(data, indent=2))


def cmd_similar(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {"url": args.url, "numResults": args.num}
    if args.exclude_source_domain:
        body["excludeSourceDomain"] = True
    if args.include_domain:
        body["includeDomains"] = args.include_domain
    if args.exclude_domain:
        body["excludeDomains"] = args.exclude_domain
    contents = _build_contents(args)
    if contents:
        body["contents"] = contents
    data = _post("/findSimilar", body)
    print(json.dumps(data, indent=2))


def cmd_contents(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {"urls": args.urls}
    if args.text:
        body["text"] = {"maxCharacters": args.max_chars} if args.max_chars else True
    if args.highlights:
        body["highlights"] = True
    if args.summary is not None:
        body["summary"] = {"query": args.summary} if args.summary else True
    # default to text if nothing requested
    if not any(k in body for k in ("text", "highlights", "summary")):
        body["text"] = True
    data = _post("/contents", body)
    print(json.dumps(data, indent=2))


def cmd_research(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {"instructions": args.topic, "model": args.model}
    data = _post("/research/v1", body, timeout=RESEARCH_TIMEOUT)
    task_id = data.get("researchId") or data.get("id")

    if not args.wait:
        print(json.dumps(data, indent=2))
        if task_id:
            print(f"\nPoll with: exa research status {task_id}", file=sys.stderr)
        return

    if not task_id:
        print("No researchId returned; cannot poll.", file=sys.stderr)
        print(json.dumps(data, indent=2))
        sys.exit(1)

    deadline = time.time() + RESEARCH_MAX_WAIT
    last_status: str | None = None
    while time.time() < deadline:
        status_data = _get(f"/research/v1/{task_id}")
        status = status_data.get("status")
        if status != last_status:
            print(f"[research {task_id}] status={status}", file=sys.stderr)
            last_status = status
        if status in ("completed", "failed", "canceled"):
            print(json.dumps(status_data, indent=2))
            if status != "completed":
                sys.exit(2)
            return
        time.sleep(RESEARCH_POLL_INTERVAL)

    print(f"Timed out after {RESEARCH_MAX_WAIT:.0f}s. Poll later with `exa research status {task_id}`.", file=sys.stderr)
    sys.exit(3)


def cmd_research_status(args: argparse.Namespace) -> None:
    data = _get(f"/research/v1/{args.id}")
    print(json.dumps(data, indent=2))


# --------------------------------------------------------------------------- #
# Argparse
# --------------------------------------------------------------------------- #


def _add_content_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--text", action="store_true", help="Include full page text in results")
    p.add_argument("--highlights", action="store_true", help="Include relevant highlights")
    p.add_argument(
        "--summary",
        nargs="?",
        const="",
        default=None,
        metavar="QUERY",
        help="Include LLM-generated summary; optional query focuses the summary",
    )
    p.add_argument("--max-chars", type=int, default=None, help="Max characters of text per result")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exa", description="Exa AI search & research CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # auth
    auth = sub.add_parser("auth", help="Manage Exa API key")
    auth_sub = auth.add_subparsers(dest="auth_cmd", required=True)
    auth_setup_p = auth_sub.add_parser("setup", help="Save API key to ~/.exa/config.json")
    auth_setup_p.add_argument("--api-key", required=True)
    auth_sub.add_parser("status", help="Show auth status")

    # search
    s = sub.add_parser("search", help="Search the web")
    s.add_argument("query")
    s.add_argument("--num", type=int, default=10, help="Number of results (default 10)")
    s.add_argument("--type", choices=["auto", "fast", "neural", "keyword"], default="auto")
    s.add_argument("--category", default=None, help="Filter by category (e.g. 'research paper', 'news')")
    s.add_argument("--include-domain", action="append", default=None, help="Include domain (repeatable)")
    s.add_argument("--exclude-domain", action="append", default=None, help="Exclude domain (repeatable)")
    s.add_argument("--start-published", default=None, help="YYYY-MM-DD")
    s.add_argument("--end-published", default=None, help="YYYY-MM-DD")
    _add_content_flags(s)

    # answer
    a = sub.add_parser("answer", help="Get a cited answer to a question")
    a.add_argument("question")
    a.add_argument("--text", action="store_true", help="Include full text of citations")

    # similar
    sim = sub.add_parser("similar", help="Find pages similar to a URL")
    sim.add_argument("url")
    sim.add_argument("--num", type=int, default=10)
    sim.add_argument("--exclude-source-domain", action="store_true")
    sim.add_argument("--include-domain", action="append", default=None)
    sim.add_argument("--exclude-domain", action="append", default=None)
    _add_content_flags(sim)

    # contents
    c = sub.add_parser("contents", help="Fetch text/highlights/summary for URLs")
    c.add_argument("urls", nargs="+")
    c.add_argument("--text", action="store_true", help="Include full text (default if no other flag set)")
    c.add_argument("--highlights", action="store_true")
    c.add_argument(
        "--summary",
        nargs="?",
        const="",
        default=None,
        metavar="QUERY",
    )
    c.add_argument("--max-chars", type=int, default=None)

    # research
    r = sub.add_parser("research", help="Deep research (async)")
    r_sub = r.add_subparsers(dest="research_cmd")

    # default: `exa research <topic>` → start task
    r.add_argument("topic", nargs="?", help="Research topic / instructions")
    r.add_argument(
        "--model",
        choices=["exa-research-fast", "exa-research", "exa-research-pro"],
        default="exa-research",
    )
    r.add_argument("--wait", action="store_true", help="Poll until task completes (up to 10 min)")

    # `exa research status <id>`
    r_status = r_sub.add_parser("status", help="Poll a research task by ID")
    r_status.add_argument("id")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "auth":
        if args.auth_cmd == "setup":
            auth_setup(args.api_key)
        elif args.auth_cmd == "status":
            auth_status()
        return

    if args.command == "search":
        cmd_search(args)
    elif args.command == "answer":
        cmd_answer(args)
    elif args.command == "similar":
        cmd_similar(args)
    elif args.command == "contents":
        cmd_contents(args)
    elif args.command == "research":
        if getattr(args, "research_cmd", None) == "status":
            cmd_research_status(args)
        else:
            if not args.topic:
                parser.error("exa research requires a topic (or use `exa research status <id>`)")
            cmd_research(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
