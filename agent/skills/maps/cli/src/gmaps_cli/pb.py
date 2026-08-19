"""The `pb` protobuf-in-a-query-param plumbing for the search RPC.

Search takes two GETs: fetch the search page for a per-session token, then call the search RPC
with that token slotted into a captured `pb` template. When Google changes the template these
helpers are where it is re-pinned (recapture with the dev harness under `tools/`).
"""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

ENVELOPE_PREFIX = ")]}'"
_TEMPLATE_PATH = Path(__file__).with_name("search_pb.txt")
_TOKEN_RE = re.compile(r'"([A-Za-z0-9_-]{22,24})"')


def strip_envelope(raw: str) -> str:
    """Google prefixes RPC JSON with `)]}'` to defeat JSON hijacking. Drop it before parsing."""
    body = raw.removeprefix(ENVELOPE_PREFIX)
    return body.lstrip("\n")


def _full_array(html: str, marker: str) -> str:
    start = html.index(marker)
    lb = html.index("[", start)
    depth = 0
    in_str = False
    esc = False
    for i in range(lb, len(html)):
        char = html[i]
        if in_str:
            if esc:
                esc = False
            elif char == "\\":
                esc = True
            elif char == '"':
                in_str = False
            continue
        if char == '"':
            in_str = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return html[lb : i + 1]
    raise ValueError("unbalanced APP_INITIALIZATION_STATE array")


def extract_session_token(page_html: str) -> str:
    """The per-session token lives in APP_INITIALIZATION_STATE[3][1] (a )]}'-prefixed string)."""
    state = json.loads(_full_array(page_html, "APP_INITIALIZATION_STATE"))
    section = state[3][1]
    if not isinstance(section, str):
        raise ValueError("session-token section is not a string")
    meta = json.loads(strip_envelope(section))
    match = _TOKEN_RE.search(json.dumps(meta))
    if match is None:
        raise ValueError("no session token found in page")
    return match.group(1)


def build_search_pb(query: str, token: str) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8").strip()
    return template.replace("{QUERY}", urllib.parse.quote(query)).replace("{TOKEN}", token)
