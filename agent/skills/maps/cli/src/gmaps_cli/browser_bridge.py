"""The signed-in-browser transport for the list commands: drives Google Maps through `browser exec`.

The only module that spawns the browser skill. Each call runs `browser exec --session default`
with a small Python program on stdin: the program reuses (or opens) a Google Maps tab, then runs
one in-page `fetch` against a `/maps/preview/entitylist/` RPC and prints its result. So the page's
cookies and origin auth apply with no token or cookie handling here. Reads are cookie-authed
alone. A write also needs the page's session token plus one of a pool of server-issued
consistency tokens the page carries, and each write action accepts only its own token, so a write
is one program that reads the tokens and tries the pool in the page until one lands. Signed-out is
a structured result, not a scraped string. Every other maps command stays on the unauthenticated
`client.py` path.
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

# The whole write in one program: read the tokens, then fetch once per pooled consistency token
# until one is accepted, and print the envelope of the last attempt. A page with no tokens prints a
# signed-out envelope, so the caller reads one shape whatever stopped the write. The pb arrives as
# a template whose two placeholders the program fills per attempt.
_WRITE_PROGRAM = (
    _TAB_PROGRAM
    + """import json
tokens = js({tokens_js!r})
session = tokens["session_token"] if isinstance(tokens, dict) and isinstance(tokens["session_token"], str) else ""
pool = [t for t in tokens["pool"] if isinstance(t, str)] if isinstance(tokens, dict) and isinstance(tokens["pool"], list) else []
envelope = {{"signed_in": bool(session) and bool(pool), "status": 0, "body": ""}}
for consistency in pool if session else []:
    pb = {pb_template!r}.replace("__SESSION__", session).replace("__CONSISTENCY__", consistency)
    envelope = js({fetch_js!r}.replace("__PB__", pb))
    if not envelope["signed_in"] or envelope["status"] == 200:
        break
print(json.dumps(envelope))
"""
)


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
    """The in-page JS returns {signed_in, status, body}; the program JSON-encodes it. Only a
    signed-in envelope comes back: a signed-out page is the one failure every caller shares."""
    data = json.loads(raw)
    if not isinstance(data, dict) or "signed_in" not in data or "status" not in data or "body" not in data:
        raise BrowserUnavailableError(f"unexpected browser exec output: {raw[:120]!r}")
    signed_in, status, body = data["signed_in"], data["status"], data["body"]
    if not isinstance(signed_in, bool) or not isinstance(status, int) or not isinstance(body, str):
        raise BrowserUnavailableError(f"malformed evaluate envelope: {raw[:120]!r}")
    if not signed_in:
        raise SignedOutError(f"not signed into Google (status {status})")
    return _Envelope(signed_in=signed_in, status=status, body=body)


def _fetch(op: str, pb: str) -> _Envelope:
    js = _FETCH_JS.format(op=op, pb=pb)
    return _parse_envelope(_exec(_FETCH_PROGRAM.format(js=js)))


def entitylist_get(op: str, pb: str) -> object:
    return json.loads(strip_envelope(_fetch(op, pb).body))


def write_program(op: str, build_pb: Callable[[str, str], str]) -> str:
    """The one program a write runs: `build_pb` is called once with the two placeholders the program
    fills in the page, so the pb shape stays with its Python owner."""
    pb_template = build_pb("__SESSION__", "__CONSISTENCY__")
    fetch_js = _FETCH_JS.format(op=op, pb="__PB__")
    return _WRITE_PROGRAM.format(tokens_js=_TOKENS_JS, pb_template=pb_template, fetch_js=fetch_js)


def entitylist_write(op: str, build_pb: Callable[[str, str], str]) -> object:
    """Run a write RPC in one program, trying each pooled consistency token until one is accepted.

    `build_pb(session_token, consistency_token)` returns the `pb` for one attempt. A rejected token
    returns a harmless 400 (no mutation); the first 200 is the applied write.
    """
    envelope = _parse_envelope(_exec(write_program(op, build_pb)))
    if envelope.status == 200:
        return json.loads(strip_envelope(envelope.body))
    raise WriteRejectedError(f"{op}: no consistency token accepted; the write pb may have drifted")
