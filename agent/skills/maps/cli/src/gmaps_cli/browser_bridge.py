"""The signed-in-browser transport for the list commands: shells the `browser` CLI.

The only module that spawns the browser skill. Each call runs one in-page `fetch` against a
`/maps/preview/entitylist/` RPC through `browser evaluate`, so the page's cookies and origin auth
apply with no token or cookie handling here. Reads are cookie-authed alone. A write also needs the
page's session token plus one of a pool of server-issued consistency tokens the page carries, and
each write action accepts only its own token, so `entitylist_write` tries the pool until one lands.
Signed-out is a structured result, not a scraped string. Every other maps command stays on the
unauthenticated `client.py` path.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from .pb import extract_session_token, strip_envelope

_MAPS_URL = "https://www.google.com/maps"
_TOKEN_PAGE = "/maps/search/coffee?hl=en"
_CONSISTENCY_RE = re.compile(r"AMAbHI[A-Za-z0-9_-]+:\d+")


class SignedOutError(RuntimeError):
    """The browser page is not signed into Google; the agent must sign in via handover."""


class BrowserUnavailableError(RuntimeError):
    """The `browser` CLI is missing or its daemon is not running."""


class WriteRejectedError(RuntimeError):
    """No consistency token was accepted; the write pb likely drifted."""


@dataclass
class _Envelope:
    signed_in: bool
    status: int
    body: str


def _browser_bin() -> str:
    return os.environ["MAPS_BROWSER_BIN"] if "MAPS_BROWSER_BIN" in os.environ else "browser"


def _run(*args: str) -> str:
    env = dict(os.environ)
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":99"
    try:
        result = subprocess.run([_browser_bin(), *args], capture_output=True, text=True, env=env, check=False)
    except FileNotFoundError as exc:
        raise BrowserUnavailableError(f"browser CLI not found: {exc}") from exc
    if result.returncode != 0:
        raise BrowserUnavailableError(f"browser {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


_FETCH_JS = """(async () => {{
  const r = await fetch("/maps/preview/entitylist/{op}?authuser=0&hl=en&pb={pb}", {{credentials:"include", headers:{{"x-same-domain":"1"}}}});
  const body = await r.text();
  const walled = (r.redirected && r.url.includes("accounts.google.com")) || r.status === 401 || r.status === 302;
  return {{signed_in: !walled, status: r.status, body}};
}})()"""

_HTML_JS = """(async () => {{
  const r = await fetch("{page}", {{credentials:"include"}});
  return await r.text();
}})()"""


def _parse_envelope(raw: str) -> _Envelope:
    """The in-page JS returns {signed_in, status, body}; `browser evaluate` JSON-encodes it."""
    data = json.loads(raw)
    if not isinstance(data, dict) or "signed_in" not in data or "status" not in data or "body" not in data:
        raise BrowserUnavailableError(f"unexpected browser evaluate output: {raw[:120]!r}")
    signed_in, status, body = data["signed_in"], data["status"], data["body"]
    if not isinstance(signed_in, bool) or not isinstance(status, int) or not isinstance(body, str):
        raise BrowserUnavailableError(f"malformed evaluate envelope: {raw[:120]!r}")
    return _Envelope(signed_in=signed_in, status=status, body=body)


def _ensure_tab() -> None:
    _run("open", _MAPS_URL)


def _fetch(op: str, pb: str) -> _Envelope:
    return _parse_envelope(_run("evaluate", _FETCH_JS.format(op=op, pb=pb)))


def entitylist_get(op: str, pb: str) -> object:
    _ensure_tab()
    envelope = _fetch(op, pb)
    if not envelope.signed_in:
        raise SignedOutError(f"not signed into Google (status {envelope.status})")
    return json.loads(strip_envelope(envelope.body))


def _page_tokens() -> tuple[str, list[str]]:
    """The session token plus the ordered, de-duplicated consistency-token pool from the maps page."""
    html = json.loads(_run("evaluate", _HTML_JS.format(page=_TOKEN_PAGE)))
    try:
        session = extract_session_token(html)
    except (ValueError, KeyError) as exc:
        raise SignedOutError(f"no session token on the maps page (signed out?): {exc}") from exc
    pool = list(dict.fromkeys(_CONSISTENCY_RE.findall(html)))
    if not pool:
        raise SignedOutError("no consistency tokens on the maps page (signed out?)")
    return session, pool


def entitylist_write(op: str, build_pb: Callable[[str, str], str]) -> object:
    """Run a write RPC, trying each pooled consistency token until one is accepted.

    `build_pb(session_token, consistency_token)` returns the `pb` for one attempt. A rejected token
    returns a harmless 400 (no mutation); the first 200 is the applied write.
    """
    _ensure_tab()
    session, pool = _page_tokens()
    for consistency in pool:
        envelope = _fetch(op, build_pb(session, consistency))
        if not envelope.signed_in:
            raise SignedOutError(f"not signed into Google (status {envelope.status})")
        if envelope.status == 200:
            return json.loads(strip_envelope(envelope.body))
    raise WriteRejectedError(f"{op}: no consistency token accepted; the write pb may have drifted")
