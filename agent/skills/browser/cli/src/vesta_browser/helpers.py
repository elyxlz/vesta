"""Browser control primitives. Edit, extend — this file is yours.

Everything here relays through the per-session daemon over /tmp/vesta-browser-<session>.sock,
which holds one WebDriver BiDi websocket to Camoufox. The agent can edit this file at
runtime; `uv tool install --editable` means changes are picked up on the next `browser`
invocation without reinstall.
"""

from __future__ import annotations

import base64
import gzip
import json
import re
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from .admin import send
from .daemon import INTERNAL_URL_PREFIXES

# WebDriver key code points for named keys (BiDi input uses raw unicode values).
SPECIAL_KEYS = {
    "Enter": "",
    "Tab": "",
    "Backspace": "",
    "Escape": "",
    "Delete": "",
    " ": " ",
    "ArrowLeft": "",
    "ArrowUp": "",
    "ArrowRight": "",
    "ArrowDown": "",
    "Home": "",
    "End": "",
    "PageUp": "",
    "PageDown": "",
}

MODIFIER_KEYS = {"Alt": "", "Control": "", "Meta": "", "Shift": ""}
MODIFIER_BITS = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}
MOUSE_BUTTONS = {"left": 0, "middle": 1, "right": 2}


# ── Core BiDi relay ────────────────────────────────────────────


def bidi(method: str, **params) -> dict:
    """Raw BiDi. `bidi('browsingContext.navigate', url='...')`. The daemon injects the
    current context where the command shape needs one. Escape hatch for anything not
    wrapped here."""
    resp = send({"method": method, "params": params})
    return resp["result"] if "result" in resp else {}


def drain_events() -> list[dict]:
    """Return and clear buffered BiDi events (load, dialogs, console, etc)."""
    return send({"meta": "drain_events"})["events"]


def pending_dialog() -> dict | None:
    """If a native user prompt is open, returns its params. Otherwise None."""
    resp = send({"meta": "pending_dialog"})
    return resp["dialog"] if "dialog" in resp else None


def current_context_id() -> str | None:
    resp = send({"meta": "context"})
    return resp["context"] if "context" in resp else None


def _set_context(context_id: str) -> None:
    send({"meta": "set_context", "context": context_id})


# ── JS evaluation ──────────────────────────────────────────────


def _eval(expression: str, context: str | None = None, await_promise: bool = True) -> dict:
    params: dict = {"expression": expression, "awaitPromise": await_promise}
    if context:
        params["target"] = {"context": context}
    return bidi("script.evaluate", **params)


def _eval_value(expression: str, context: str | None = None):
    """Evaluate an expression whose completion value is a JSON string; return it parsed."""
    r = _eval(expression, context)
    if "type" not in r:
        raise RuntimeError(f"unexpected script.evaluate response: {r!r}")
    if r["type"] == "exception":
        detail = r["exceptionDetails"]["text"] if "exceptionDetails" in r else "unknown"
        raise RuntimeError(f"js exception: {detail}")
    value = r["result"]
    if value["type"] in ("undefined", "null"):
        return None
    return json.loads(value["value"])


def js(expression: str, target_id: str | None = None):
    """Evaluate a JS expression. `target_id` to run inside an iframe/tab context."""
    wrapped = f"Promise.resolve({expression}).then(v => JSON.stringify(v === undefined ? null : v))"
    return _eval_value(wrapped, context=target_id)


# ── Navigation ─────────────────────────────────────────────────


def goto(url: str) -> dict:
    """Navigate the current tab to `url`."""
    return bidi("browsingContext.navigate", url=url, wait="complete")


def reload() -> dict:
    return bidi("browsingContext.reload", wait="complete")


def _go_history(step: int) -> dict:
    try:
        return bidi("browsingContext.traverseHistory", delta=step)
    except RuntimeError:
        # No history entry that far — mirror the old out-of-range no-op.
        return {}


def back() -> dict:
    return _go_history(-1)


def forward() -> dict:
    return _go_history(1)


def new_tab(url: str = "about:blank") -> str:
    """Create a new tab, switch to it, optionally navigate. Returns its context id."""
    ctx = bidi("browsingContext.create", type="tab")["context"]
    _set_context(ctx)
    if url and url != "about:blank":
        goto(url)
    return ctx


def switch_tab(target_id: str) -> str:
    bidi("browsingContext.activate", context=target_id)
    _set_context(target_id)
    return target_id


def list_tabs(include_internal: bool = True) -> list[dict]:
    out = []
    for node in bidi("browsingContext.getTree")["contexts"]:
        url = node["url"] if "url" in node else ""
        if not include_internal and url.startswith(INTERNAL_URL_PREFIXES):
            continue
        try:
            title = js("document.title", target_id=node["context"]) or ""
        except RuntimeError:
            title = ""
        out.append({"target_id": node["context"], "title": title, "url": url})
    return out


def current_tab() -> dict:
    ctx = current_context_id()
    try:
        info = js("({url:location.href,title:document.title})") or {}
    except RuntimeError:
        info = {}
    return {
        "target_id": ctx,
        "url": info["url"] if "url" in info else "",
        "title": info["title"] if "title" in info else "",
    }


def ensure_real_tab() -> dict | None:
    """Switch to a real page if currently on an internal page or stale context."""
    tabs = list_tabs(include_internal=False)
    if not tabs:
        return None
    cur = current_tab()
    if cur["url"] and not cur["url"].startswith(INTERNAL_URL_PREFIXES):
        return cur
    switch_tab(tabs[0]["target_id"])
    return tabs[0]


def iframe_target(url_substring: str) -> str | None:
    """First iframe (child) context whose URL contains the substring."""

    def walk(nodes: list[dict], depth: int) -> str | None:
        for node in nodes:
            url = node["url"] if "url" in node else ""
            if depth > 0 and url_substring in url:
                return node["context"]
            children = node["children"] if node.get("children") else []
            found = walk(children, depth + 1)
            if found:
                return found
        return None

    return walk(bidi("browsingContext.getTree")["contexts"], 0)


def close_tab(target_id: str) -> None:
    bidi("browsingContext.close", context=target_id)


# ── Input (coordinate-based via input.performActions) ─────────


def _perform(sources: list[dict]) -> None:
    bidi("input.performActions", actions=sources)


def click(x: float, y: float, button: str = "left", clicks: int = 1) -> None:
    """Coordinate click. Goes through iframes/shadow/cross-origin at the input level.

    Prefer this over ref-based clicks when:
    - Target is inside a shadow DOM / cross-origin iframe
    - Site's accessibility tree is misleading
    - You already know the pixel position from a screenshot
    """
    btn = MOUSE_BUTTONS[button] if button in MOUSE_BUTTONS else 0
    actions: list[dict] = [{"type": "pointerMove", "x": int(x), "y": int(y)}]
    for _ in range(clicks):
        actions.append({"type": "pointerDown", "button": btn})
        actions.append({"type": "pointerUp", "button": btn})
    _perform([{"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": actions}])


def type_text(text: str) -> None:
    """Insert text into the focused element."""
    actions: list[dict] = []
    for ch in text:
        actions.append({"type": "keyDown", "value": ch})
        actions.append({"type": "keyUp", "value": ch})
    _perform([{"type": "key", "id": "kbd", "actions": actions}])


def press_key(key: str, modifiers: int | list[str] = 0) -> None:
    """Press a key. `modifiers` can be the legacy CDP bitfield int or a list like ['Control', 'Shift']."""
    if isinstance(modifiers, int):
        mods = [name for name, bit in MODIFIER_BITS.items() if modifiers & bit]
    else:
        mods = [m for m in modifiers if m in MODIFIER_KEYS]
    value = SPECIAL_KEYS[key] if key in SPECIAL_KEYS else key
    actions: list[dict] = [{"type": "keyDown", "value": MODIFIER_KEYS[m]} for m in mods]
    actions.append({"type": "keyDown", "value": value})
    actions.append({"type": "keyUp", "value": value})
    actions.extend({"type": "keyUp", "value": MODIFIER_KEYS[m]} for m in reversed(mods))
    _perform([{"type": "key", "id": "kbd", "actions": actions}])


def scroll(x: float, y: float, dy: float = -300, dx: float = 0) -> None:
    _perform(
        [{"type": "wheel", "id": "wheel", "actions": [{"type": "scroll", "x": int(x), "y": int(y), "deltaX": int(dx), "deltaY": int(dy)}]}]
    )


# ── Input (ref-based via the in-page snapshot map) ────────────


def _norm_ref(ref: str) -> str:
    return ref[4:] if ref.startswith("ref=") else ref.removeprefix("@")


def _resolve_center(ref: str) -> tuple[float, float]:
    """Scroll a ref into view and return its viewport center via the in-page ref map."""
    box = _eval_value(f"JSON.stringify(globalThis.__vestaResolveRef({json.dumps(_norm_ref(ref))}))")
    if not box or not box["found"]:
        raise RuntimeError(f"unknown ref {ref!r}. Take a fresh snapshot and use a ref from that output.")
    return box["x"], box["y"]


def click_ref(ref: str, button: str = "left", clicks: int = 1) -> None:
    """Click an element by ref (e.g. 'e5') from the most recent snapshot."""
    x, y = _resolve_center(ref)
    click(x, y, button=button, clicks=clicks)


def type_ref(ref: str, text: str, submit: bool = False, slowly: bool = False) -> None:
    found = _eval_value(f"JSON.stringify(globalThis.__vestaFocusRef({json.dumps(_norm_ref(ref))}))")
    if not found or not found["found"]:
        raise RuntimeError(f"unknown ref {ref!r}. Take a fresh snapshot and use a ref from that output.")
    if slowly:
        for ch in text:
            press_key(ch)
            time.sleep(0.075)
    else:
        type_text(text)
    if submit:
        press_key("Enter")


def hover_ref(ref: str) -> None:
    x, y = _resolve_center(ref)
    _perform(
        [
            {
                "type": "pointer",
                "id": "mouse",
                "parameters": {"pointerType": "mouse"},
                "actions": [{"type": "pointerMove", "x": int(x), "y": int(y)}],
            }
        ]
    )


def scroll_to_ref(ref: str) -> None:
    """Scroll a ref into view (the resolver centers it in the viewport)."""
    _resolve_center(ref)


# ── Visual ────────────────────────────────────────────────────

# Firefox BiDi captures png/jpeg only; webp maps to jpeg (also small, lossy).
_FMT_MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/jpeg"}


def screenshot(
    path: str = "/tmp/screenshot.png",
    full_page: bool = False,
    image_format: str = "png",
    region: tuple[float, float, float, float] | None = None,
    quality: int | None = None,
) -> str:
    """Capture a screenshot via BiDi. `image_format` accepts 'png', 'jpeg', or 'webp'
    (webp is captured as jpeg). `region` is (x, y, width, height) for a clip rectangle.
    `quality` (0-100) applies to jpeg/webp."""
    if image_format not in ("png", "jpeg", "webp"):
        raise ValueError(f"screenshot format must be png/jpeg/webp, got {image_format!r}")
    fmt: dict = {"type": _FMT_MIME[image_format]}
    if quality is not None and image_format in ("jpeg", "webp"):
        fmt["quality"] = max(0.0, min(1.0, quality / 100.0))
    params: dict = {"origin": "document" if full_page else "viewport", "format": fmt}
    if region is not None:
        x, y, w, h = region
        if w <= 0 or h <= 0:
            raise ValueError("screenshot region width and height must be positive")
        params["clip"] = {"type": "box", "x": x, "y": y, "width": w, "height": h}
    r = bidi("browsingContext.captureScreenshot", **params)
    Path(path).write_bytes(base64.b64decode(r["data"]))
    return path


def pdf(path: str = "/tmp/page.pdf") -> str:
    r = bidi("browsingContext.print")
    Path(path).write_bytes(base64.b64decode(r["data"]))
    return path


def page_info() -> dict:
    """{url, title, w, h, sx, sy, pw, ph}. If a native dialog is open, returns {dialog: ...}."""
    dialog = pending_dialog()
    if dialog:
        return {"dialog": dialog}
    return js(
        "({url:location.href,title:document.title,w:innerWidth,h:innerHeight,"
        "sx:scrollX,sy:scrollY,pw:document.documentElement.scrollWidth,ph:document.documentElement.scrollHeight})"
    )


def set_viewport(width: int, height: int) -> dict:
    return bidi("browsingContext.setViewport", viewport={"width": width, "height": height})


# ── JS / DOM ──────────────────────────────────────────────────


def upload_file(selector: str, path: str | list[str]) -> None:
    """Set files on a file-input element found by CSS selector."""
    paths = [path] if isinstance(path, str) else list(path)
    r = bidi("script.evaluate", expression=f"document.querySelector({json.dumps(selector)})", awaitPromise=False, resultOwnership="root")
    if r["type"] == "exception" or r["result"]["type"] == "null":
        raise RuntimeError(f"no element for {selector}")
    bidi("input.setFiles", element={"sharedId": r["result"]["sharedId"]}, files=paths)


# ── Waiting ───────────────────────────────────────────────────


def wait(seconds: float = 1.0) -> None:
    time.sleep(seconds)


def _poll_until(predicate: Callable[[], bool], timeout: float, poll: float) -> bool:
    """Poll `predicate` until it is truthy or `timeout` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    return False


def wait_for_load(timeout: float = 15.0) -> bool:
    """Poll document.readyState == 'complete'."""
    return _poll_until(lambda: js("document.readyState") == "complete", timeout, 0.3)


def wait_for_text(text: str, timeout: float = 20.0, poll: float = 0.4) -> bool:
    expr = f"document.body && document.body.innerText.indexOf({json.dumps(text)}) >= 0"
    return _poll_until(lambda: bool(js(expr)), timeout, poll)


def wait_for_url(pattern: str, timeout: float = 20.0, poll: float = 0.3) -> bool:
    """Match a URL glob-ish pattern with `*` wildcards."""
    import fnmatch

    def matched() -> bool:
        try:
            info = page_info()
        except RuntimeError:
            return False
        return "url" in info and fnmatch.fnmatch(info["url"], pattern)

    return _poll_until(matched, timeout, poll)


# ── Network / HTTP shortcut ───────────────────────────────────


def http_get(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0) -> str:
    """Pure HTTP — no browser. Use for static pages / JSON APIs.

    Pattern: `ThreadPoolExecutor(...)` + `http_get` for bulk. Much faster than navigating.
    """
    hdrs = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if "Content-Encoding" in r.headers and r.headers["Content-Encoding"] == "gzip":
            data = gzip.decompress(data)
        return data.decode()


def fetch_navigate(url: str, timeout: float = 20.0) -> str:
    """Fetch a page through the stealth browser (full Camoufox fingerprint), returning
    its rendered text. Use when a plain http_get is blocked or needs JS rendering."""
    goto(url)
    wait_for_load(timeout=timeout)
    return js("document.body ? document.body.innerText : ''") or ""


# ── Recipes banner on navigation ──────────────────────────────


def _skills_root() -> Path:
    # helpers.py is src/vesta_browser/helpers.py, so parents[3] is agent/skills/browser/.
    return Path(__file__).resolve().parents[3]


def _declared_hosts(path: Path) -> set[str]:
    """Hosts a recipe claims via a leading `hosts:` frontmatter line (comma/space separated).
    Lets one recipe cover several domains (e.g. a job board on many country TLDs) that no single
    directory name maps to."""
    front = re.match(r"^---\n(.*?)\n---", path.read_text(encoding="utf-8", errors="ignore"), re.DOTALL)
    if not front:
        return set()
    line = re.search(r"^hosts:\s*(.+)$", front.group(1), re.MULTILINE)
    if not line:
        return set()
    raw = line.group(1).strip().strip("[]")
    return {h.strip().strip("\"'").removeprefix("www.") for h in re.split(r"[,\s]+", raw) if h.strip()}


def recipes_for(url: str) -> list[str]:
    """Matching domain-skill files for this URL. Returns relative paths."""
    host = (urlparse(url).hostname or "").lstrip(".").removeprefix("www.")
    if not host:
        return []
    root = _skills_root() / "domain-skills"
    if not root.is_dir():
        return []
    # Try exact host, then the bare second-level domain (foo.com from sub.foo.com).
    candidates = [host]
    if host.count(".") >= 2:
        parts = host.split(".")
        candidates.append(".".join(parts[-2:]))
    for candidate in candidates:
        d = root / candidate
        if d.is_dir():
            return sorted(f"domain-skills/{candidate}/{p.name}" for p in d.rglob("*.md"))
    # No host-named directory: fall back to recipes that declare this host in frontmatter.
    wanted = set(candidates)
    return sorted(f"domain-skills/{p.relative_to(root)}" for p in root.rglob("*.md") if wanted & _declared_hosts(p))


def recipe_banner(url: str) -> str:
    files = recipes_for(url)
    if not files:
        return ""
    lines = [f"📝 Recipes for {urlparse(url).hostname}:"]
    lines += [f"  - {name}" for name in files]
    lines.append(f"  Read via: cat {_skills_root()}/<path>")
    return "\n".join(lines)
