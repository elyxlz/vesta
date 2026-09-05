"""The signed-in-browser transport for the list commands: drives Google Maps through `browser exec`.

The only module that spawns the browser skill. Each call runs `browser exec --session default`
with a small Python program on stdin: the program reuses (or opens) a Google Maps tab, then runs
one in-page `fetch` against a `/maps/preview/entitylist/` RPC and prints its result. So the page's
cookies and origin auth apply with no token or cookie handling here. Reads are cookie-authed
alone. A write also needs the page's session token plus one of a pool of server-issued
consistency tokens the page carries, and each write action accepts only its own token, so
`entitylist_write` tries the pool until one lands. Signed-out is a structured result, not a
scraped string. Every other maps command stays on the unauthenticated `client.py` path.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from .pb import SESSION_TOKEN_RE, strip_envelope

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


_TAB_PROGRAM = """
tabs = [t for t in list_tabs() if t["url"].startswith("https://www.google.com/maps")]
if tabs:
    switch_tab(tabs[0]["target_id"])
else:
    new_tab("https://www.google.com/maps")
    wait_for_load()
"""

_JS_PROGRAM = "import json\nprint(json.dumps(js({js!r})))\n"
_FETCH_PROGRAM = _TAB_PROGRAM + _JS_PROGRAM

_FETCH_JS = """(async () => {{
  const r = await fetch("/maps/preview/entitylist/{op}?authuser=0&hl=en&pb={pb}", {{credentials:"include", headers:{{"x-same-domain":"1"}}}});
  const body = await r.text();
  const walled = (r.redirected && r.url.includes("accounts.google.com")) || r.status === 401 || r.status === 302;
  return {{signed_in: !walled, status: r.status, body}};
}})()"""

# Reads the tokens inside the page. The token page is far past the daemon's stdout cap, so shipping
# the document out would truncate it. The session-token rule is `pb.extract_session_token` ported to
# JS over the same two patterns, which are formatted in from their Python owners.
_TOKENS_JS_TEMPLATE = r"""(async () => {
  const text = await (await fetch("__PAGE__", {credentials:"include"})).text();
  const pool = [...new Set(text.match(/__CONSISTENCY__/g) || [])];
  let session = "";
  const start = text.indexOf("APP_INITIALIZATION_STATE");
  const open = start < 0 ? -1 : text.indexOf("[", start);
  let depth = 0, inStr = false, esc = false, close = -1;
  for (let i = open; open >= 0 && i < text.length; i++) {
    const c = text[i];
    if (inStr) {
      if (esc) { esc = false; } else if (c === "\\") { esc = true; } else if (c === '"') { inStr = false; }
      continue;
    }
    if (c === '"') { inStr = true; }
    else if (c === "[") { depth++; }
    else if (c === "]") { depth--; if (depth === 0) { close = i; break; } }
  }
  if (close > 0) {
    try {
      const section = JSON.parse(text.slice(open, close + 1))[3][1];
      const meta = JSON.parse(String(section).replace(/^\)\]\}'/, "").replace(/^\n+/, ""));
      const found = JSON.stringify(meta).match(/__TOKEN__/);
      if (found) { session = found[1]; }
    } catch (err) { session = ""; }
  }
  return {session_token: session, pool};
})()"""

_TOKENS_JS = (
    _TOKENS_JS_TEMPLATE.replace("__PAGE__", _TOKEN_PAGE)
    .replace("__CONSISTENCY__", _CONSISTENCY_RE.pattern)
    .replace("__TOKEN__", SESSION_TOKEN_RE.pattern)
)
_TOKENS_PROGRAM = _TAB_PROGRAM + _JS_PROGRAM.format(js=_TOKENS_JS)


def _exec(code: str) -> str:
    """Run `code` on the browser daemon's default Chromium session; return its captured stdout."""
    try:
        result = subprocess.run([_browser_bin(), "exec", "--session", "default"], input=code, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise BrowserUnavailableError(f"browser CLI not found: {exc}") from exc
    line = result.stdout.strip() or result.stderr.strip()
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError:
        raise BrowserUnavailableError(f"unexpected browser exec output: {line[:120]!r}") from None
    if not isinstance(envelope, dict) or "ok" not in envelope or "warnings" not in envelope:
        raise BrowserUnavailableError(f"unexpected browser exec output: {line[:120]!r}")
    if not envelope["ok"]:
        error = envelope["error"]
        message = error["message"]
        if error["code"] == "daemon_down":
            message = f"start the browser daemon: {message}"
        raise BrowserUnavailableError(message)
    if "output_truncated" in envelope["warnings"]:
        raise BrowserUnavailableError("browser output was truncated; the program must print less")
    output = envelope["output"]
    return output["stdout"].strip()


def _parse_envelope(raw: str) -> _Envelope:
    """The in-page JS returns {signed_in, status, body}; the fetch program JSON-encodes it."""
    data = json.loads(raw)
    if not isinstance(data, dict) or "signed_in" not in data or "status" not in data or "body" not in data:
        raise BrowserUnavailableError(f"unexpected browser exec output: {raw[:120]!r}")
    signed_in, status, body = data["signed_in"], data["status"], data["body"]
    if not isinstance(signed_in, bool) or not isinstance(status, int) or not isinstance(body, str):
        raise BrowserUnavailableError(f"malformed evaluate envelope: {raw[:120]!r}")
    return _Envelope(signed_in=signed_in, status=status, body=body)


def _fetch(op: str, pb: str) -> _Envelope:
    js = _FETCH_JS.format(op=op, pb=pb)
    return _parse_envelope(_exec(_FETCH_PROGRAM.format(js=js)))


def entitylist_get(op: str, pb: str) -> object:
    envelope = _fetch(op, pb)
    if not envelope.signed_in:
        raise SignedOutError(f"not signed into Google (status {envelope.status})")
    return json.loads(strip_envelope(envelope.body))


def _page_tokens() -> tuple[str, list[str]]:
    """The session token plus the ordered, de-duplicated consistency-token pool from the maps page."""
    raw = _exec(_TOKENS_PROGRAM)
    data = json.loads(raw)
    if not isinstance(data, dict) or "session_token" not in data or "pool" not in data:
        raise BrowserUnavailableError(f"unexpected browser exec output: {raw[:120]!r}")
    session, pool = data["session_token"], data["pool"]
    if not isinstance(session, str) or not isinstance(pool, list):
        raise BrowserUnavailableError(f"malformed token payload: {raw[:120]!r}")
    if not session:
        raise SignedOutError("no session token on the maps page (signed out?)")
    tokens = [token for token in pool if isinstance(token, str)]
    if not tokens:
        raise SignedOutError("no consistency tokens on the maps page (signed out?)")
    return session, tokens


def entitylist_write(op: str, build_pb: Callable[[str, str], str]) -> object:
    """Run a write RPC, trying each pooled consistency token until one is accepted.

    `build_pb(session_token, consistency_token)` returns the `pb` for one attempt. A rejected token
    returns a harmless 400 (no mutation); the first 200 is the applied write.
    """
    session, pool = _page_tokens()
    for consistency in pool:
        envelope = _fetch(op, build_pb(session, consistency))
        if not envelope.signed_in:
            raise SignedOutError(f"not signed into Google (status {envelope.status})")
        if envelope.status == 200:
            return json.loads(strip_envelope(envelope.body))
    raise WriteRejectedError(f"{op}: no consistency token accepted; the write pb may have drifted")
