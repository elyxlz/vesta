"""The signed-in-browser transport for the list commands: shells the `browser` CLI.

The only module that spawns the browser skill. Each call runs one in-page `fetch` against a
`/maps/preview/entitylist/` RPC through `browser evaluate`, so the page's cookies and origin auth
apply with no token or cookie handling here. Signed-out is a structured result, not a scraped
string. Every other maps command stays on the unauthenticated `client.py` path.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

_MAPS_URL = "https://www.google.com/maps"


class SignedOutError(RuntimeError):
    """The browser page is not signed into Google; the agent must sign in via handover."""


class BrowserUnavailableError(RuntimeError):
    """The `browser` CLI is missing or its daemon is not running."""


@dataclass
class _Envelope:
    signed_in: bool
    status: int
    body: str


def _parse_envelope(raw: str) -> _Envelope:
    """The in-page JS returns {signed_in, status, body}; `browser evaluate` JSON-encodes it."""
    data = json.loads(raw)
    if not isinstance(data, dict) or "signed_in" not in data or "status" not in data or "body" not in data:
        raise BrowserUnavailableError(f"unexpected browser evaluate output: {raw[:120]!r}")
    signed_in, status, body = data["signed_in"], data["status"], data["body"]
    if not isinstance(signed_in, bool) or not isinstance(status, int) or not isinstance(body, str):
        raise BrowserUnavailableError(f"malformed evaluate envelope: {raw[:120]!r}")
    return _Envelope(signed_in=signed_in, status=status, body=body)


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
  return {{signed_in: r.ok && !walled, status: r.status, body}};
}})()"""

_TOKEN_JS = """(() => {
  try { return window.APP_INITIALIZATION_STATE[3][1].split('"').find(s => s.length > 12 && !s.includes('/')) || ""; }
  catch (e) { return ""; }
})()"""


def _strip_xssi(body: str) -> str:
    stripped = body.lstrip()
    if stripped.startswith(")]}'"):
        return stripped.split("\n", 1)[1]
    return stripped


def _evaluate_envelope(op: str, pb: str) -> _Envelope:
    _run("open", _MAPS_URL)
    raw = _run("evaluate", _FETCH_JS.format(op=op, pb=pb))
    return _parse_envelope(raw)


def entitylist_get(op: str, pb: str) -> object:
    envelope = _evaluate_envelope(op, pb)
    if not envelope.signed_in:
        raise SignedOutError(f"not signed into Google (status {envelope.status})")
    return json.loads(_strip_xssi(envelope.body))


def session_token() -> str:
    _run("open", _MAPS_URL)
    raw = _run("evaluate", _TOKEN_JS)
    token = json.loads(raw)
    if not isinstance(token, str) or not token:
        raise BrowserUnavailableError("could not read the maps session token from the page")
    return token


def is_signed_in() -> bool:
    try:
        entitylist_get("list", "!1e3")
    except SignedOutError:
        return False
    return True
