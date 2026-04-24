"""Browser control primitives. Edit, extend — this file is yours.

Everything here relays through the per-session daemon over /tmp/vesta-browser-<session>.sock.
The agent can edit this file at runtime; `uv tool install --editable` means changes are
picked up on the next `browser` invocation without reinstall.
"""

from __future__ import annotations

import base64
import gzip
import json
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .admin import send

INTERNAL_URL_PREFIXES = (
    "chrome://",
    "chrome-untrusted://",
    "devtools://",
    "chrome-extension://",
    "about:",
)

SPECIAL_KEYS = {
    "Enter": (13, "Enter", "\r"),
    "Tab": (9, "Tab", "\t"),
    "Backspace": (8, "Backspace", ""),
    "Escape": (27, "Escape", ""),
    "Delete": (46, "Delete", ""),
    " ": (32, "Space", " "),
    "ArrowLeft": (37, "ArrowLeft", ""),
    "ArrowUp": (38, "ArrowUp", ""),
    "ArrowRight": (39, "ArrowRight", ""),
    "ArrowDown": (40, "ArrowDown", ""),
    "Home": (36, "Home", ""),
    "End": (35, "End", ""),
    "PageUp": (33, "PageUp", ""),
    "PageDown": (34, "PageDown", ""),
}

MODIFIER_BITS = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}


# ── Core CDP relay ─────────────────────────────────────────────


def cdp(method: str, session_id: str | None = None, **params) -> dict:
    """Raw CDP. `cdp('Page.navigate', url='...')`. Escape hatch for anything not wrapped here."""
    resp = send({"method": method, "params": params, "session_id": session_id})
    return resp["result"] if "result" in resp else {}


def drain_events() -> list[dict]:
    """Return and clear buffered CDP events (dialog opens, network, etc)."""
    return send({"meta": "drain_events"})["events"]


def pending_dialog() -> dict | None:
    """If a native dialog is open, returns its params. Otherwise None."""
    resp = send({"meta": "pending_dialog"})
    return resp["dialog"] if "dialog" in resp else None


def current_session_id() -> str | None:
    resp = send({"meta": "session"})
    return resp["session_id"] if "session_id" in resp else None


def _set_session(session_id: str) -> None:
    send({"meta": "set_session", "session_id": session_id})


# ── Navigation ─────────────────────────────────────────────────


def goto(url: str) -> dict:
    """Navigate the current tab to `url`."""
    return cdp("Page.navigate", url=url)


def reload() -> dict:
    return cdp("Page.reload")


def back() -> dict:
    hist = cdp("Page.getNavigationHistory")
    entries = hist["entries"]
    idx = hist["currentIndex"]
    if idx <= 0:
        return {}
    return cdp("Page.navigateToHistoryEntry", entryId=entries[idx - 1]["id"])


def forward() -> dict:
    hist = cdp("Page.getNavigationHistory")
    entries = hist["entries"]
    idx = hist["currentIndex"]
    if idx >= len(entries) - 1:
        return {}
    return cdp("Page.navigateToHistoryEntry", entryId=entries[idx + 1]["id"])


def new_tab(url: str = "about:blank") -> str:
    """Create a new tab, switch to it, optionally navigate. Returns target_id."""
    tid = cdp("Target.createTarget", url="about:blank")["targetId"]
    switch_tab(tid)
    if url and url != "about:blank":
        goto(url)
    return tid


def switch_tab(target_id: str) -> str:
    cdp("Target.activateTarget", targetId=target_id)
    sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    _set_session(sid)
    return sid


def list_tabs(include_internal: bool = True) -> list[dict]:
    out = []
    for t in cdp("Target.getTargets")["targetInfos"]:
        if t["type"] != "page":
            continue
        url = t["url"] if "url" in t else ""
        if not include_internal and url.startswith(INTERNAL_URL_PREFIXES):
            continue
        title = t["title"] if "title" in t else ""
        out.append({"target_id": t["targetId"], "title": title, "url": url})
    return out


def current_tab() -> dict:
    resp = cdp("Target.getTargetInfo")
    info = resp["targetInfo"] if "targetInfo" in resp else {}
    return {
        "target_id": info["targetId"] if "targetId" in info else None,
        "url": info["url"] if "url" in info else "",
        "title": info["title"] if "title" in info else "",
    }


def ensure_real_tab() -> dict | None:
    """Switch to a real page if currently on chrome://, omnibox popup, or stale target."""
    tabs = list_tabs(include_internal=False)
    if not tabs:
        return None
    try:
        cur = current_tab()
    except RuntimeError:
        cur = None
    if cur and cur["url"] and not cur["url"].startswith(INTERNAL_URL_PREFIXES):
        return cur
    switch_tab(tabs[0]["target_id"])
    return tabs[0]


def iframe_target(url_substring: str) -> str | None:
    """First iframe target whose URL contains the substring."""
    for t in cdp("Target.getTargets")["targetInfos"]:
        url = t["url"] if "url" in t else ""
        if t["type"] == "iframe" and url_substring in url:
            return t["targetId"]
    return None


def close_tab(target_id: str) -> None:
    cdp("Target.closeTarget", targetId=target_id)


# ── Input (coordinate-based) ──────────────────────────────────


def click(x: float, y: float, button: str = "left", clicks: int = 1) -> None:
    """Coordinate click. Goes through iframes/shadow/cross-origin at the compositor level.

    Prefer this over ref-based clicks when:
    - Target is inside a shadow DOM / cross-origin iframe
    - Site's accessibility tree is misleading
    - You already know the pixel position from a screenshot
    """
    cdp("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button=button, clickCount=clicks)
    cdp("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button=button, clickCount=clicks)


def type_text(text: str) -> None:
    """Insert text into the focused element."""
    cdp("Input.insertText", text=text)


def press_key(key: str, modifiers: int | list[str] = 0) -> None:
    """Press a key. `modifiers` can be the CDP bitfield int or a list like ['Control', 'Shift']."""
    if isinstance(modifiers, list):
        mods = 0
        for m in modifiers:
            if m in MODIFIER_BITS:
                mods |= MODIFIER_BITS[m]
        modifiers = mods
    if key in SPECIAL_KEYS:
        vk, code, text = SPECIAL_KEYS[key]
    elif len(key) == 1:
        vk, code, text = ord(key[0]), key, key
    else:
        vk, code, text = 0, key, ""
    base = {
        "key": key,
        "code": code,
        "modifiers": modifiers,
        "windowsVirtualKeyCode": vk,
        "nativeVirtualKeyCode": vk,
    }
    cdp("Input.dispatchKeyEvent", type="keyDown", **base, **({"text": text} if text else {}))
    if text and len(text) == 1:
        char_params = {k: v for k, v in base.items() if k != "text"}
        cdp("Input.dispatchKeyEvent", type="char", text=text, **char_params)
    cdp("Input.dispatchKeyEvent", type="keyUp", **base)


def scroll(x: float, y: float, dy: float = -300, dx: float = 0) -> None:
    cdp("Input.dispatchMouseEvent", type="mouseWheel", x=x, y=y, deltaX=dx, deltaY=dy)


# ── Input (ref-based via accessibility snapshot) ──────────────


def click_ref(ref: str, button: str = "left", clicks: int = 1) -> None:
    """Click an element by ref (e.g. 'e5') from the most recent snapshot."""
    from .snapshot import read_ref

    info = read_ref(_current_target_id(), ref)
    backend = info["backend_node_id"]
    _scroll_into_view(backend)
    box = _center_box(backend)
    click(box[0], box[1], button=button, clicks=clicks)


def type_ref(ref: str, text: str, submit: bool = False, slowly: bool = False) -> None:
    from .snapshot import read_ref

    info = read_ref(_current_target_id(), ref)
    backend = info["backend_node_id"]
    _scroll_into_view(backend)
    cdp("DOM.focus", backendNodeId=backend)
    if slowly:
        for ch in text:
            press_key(ch)
            time.sleep(0.075)
    else:
        type_text(text)
    if submit:
        press_key("Enter")


def hover_ref(ref: str) -> None:
    from .snapshot import read_ref

    info = read_ref(_current_target_id(), ref)
    backend = info["backend_node_id"]
    _scroll_into_view(backend)
    box = _center_box(backend)
    cdp("Input.dispatchMouseEvent", type="mouseMoved", x=box[0], y=box[1])


def _current_target_id() -> str:
    tid = current_tab()["target_id"]
    if not tid:
        raise RuntimeError("no current target")
    return tid


def _scroll_into_view(backend_node_id: int) -> None:
    try:
        cdp("DOM.scrollIntoViewIfNeeded", backendNodeId=backend_node_id)
    except RuntimeError:
        # Node may be hidden or not scrollable — click attempt will surface a better error.
        pass


def _center_box(backend_node_id: int) -> tuple[float, float]:
    resp = cdp("DOM.getBoxModel", backendNodeId=backend_node_id)
    if "model" not in resp or "content" not in resp["model"] or len(resp["model"]["content"]) < 8:
        raise RuntimeError(f"element (backendNodeId={backend_node_id}) has no box. It may be hidden, 0×0, or detached — take a fresh snapshot.")
    content = resp["model"]["content"]
    cx = (content[0] + content[4]) / 2
    cy = (content[1] + content[5]) / 2
    return cx, cy


# ── Visual ────────────────────────────────────────────────────


def screenshot(
    path: str = "/tmp/screenshot.png",
    full_page: bool = False,
    format: str = "png",
    region: tuple[float, float, float, float] | None = None,
    quality: int | None = None,
) -> str:
    """Capture a screenshot via CDP. `format` accepts 'png', 'jpeg', or 'webp'.
    `region` is (x, y, width, height) for a clip rectangle. `quality` applies to jpeg/webp."""
    if format not in ("png", "jpeg", "webp"):
        raise ValueError(f"screenshot format must be png/jpeg/webp, got {format!r}")
    params: dict = {"format": format, "captureBeyondViewport": full_page}
    if region is not None:
        x, y, w, h = region
        if w <= 0 or h <= 0:
            raise ValueError("screenshot region width and height must be positive")
        params["clip"] = {"x": x, "y": y, "width": w, "height": h, "scale": 1}
    if quality is not None and format in ("jpeg", "webp"):
        params["quality"] = quality
    r = cdp("Page.captureScreenshot", **params)
    Path(path).write_bytes(base64.b64decode(r["data"]))
    return path


def pdf(path: str = "/tmp/page.pdf") -> str:
    r = cdp("Page.printToPDF")
    Path(path).write_bytes(base64.b64decode(r["data"]))
    return path


def page_info() -> dict:
    """{url, title, w, h, sx, sy, pw, ph}. If a native dialog is open, returns {dialog: ...}."""
    dialog = pending_dialog()
    if dialog:
        return {"dialog": dialog}
    r = cdp(
        "Runtime.evaluate",
        expression="JSON.stringify({url:location.href,title:document.title,"
        "w:innerWidth,h:innerHeight,sx:scrollX,sy:scrollY,"
        "pw:document.documentElement.scrollWidth,ph:document.documentElement.scrollHeight})",
        returnByValue=True,
    )
    return json.loads(r["result"]["value"])


# ── JS / DOM ──────────────────────────────────────────────────


def js(expression: str, target_id: str | None = None):
    """Evaluate a JS expression. `target_id` to run inside an iframe target."""
    sid = None
    if target_id:
        sid = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    r = cdp(
        "Runtime.evaluate",
        session_id=sid,
        expression=expression,
        returnByValue=True,
        awaitPromise=True,
    )
    if "result" not in r or "value" not in r["result"]:
        return None
    return r["result"]["value"]


def upload_file(selector: str, path: str | list[str]) -> None:
    """Set files on a file-input element found by CSS selector."""
    paths = [path] if isinstance(path, str) else list(path)
    doc = cdp("DOM.getDocument", depth=-1)
    nid = cdp("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector=selector)["nodeId"]
    if not nid:
        raise RuntimeError(f"no element for {selector}")
    cdp("DOM.setFileInputFiles", files=paths, nodeId=nid)


# ── Waiting ───────────────────────────────────────────────────


def wait(seconds: float = 1.0) -> None:
    time.sleep(seconds)


def wait_for_load(timeout: float = 15.0) -> bool:
    """Poll document.readyState == 'complete'."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if js("document.readyState") == "complete":
            return True
        time.sleep(0.3)
    return False


def wait_for_text(text: str, timeout: float = 20.0, poll: float = 0.4) -> bool:
    deadline = time.time() + timeout
    expr = f"document.body && document.body.innerText.indexOf({json.dumps(text)}) >= 0"
    while time.time() < deadline:
        if js(expr):
            return True
        time.sleep(poll)
    return False


def wait_for_url(pattern: str, timeout: float = 20.0, poll: float = 0.3) -> bool:
    """Match a URL glob-ish pattern with `*` wildcards."""
    import fnmatch

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            info = page_info()
        except RuntimeError:
            info = {}
        if "url" in info and fnmatch.fnmatch(info["url"], pattern):
            return True
        time.sleep(poll)
    return False


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


# ── Recipes banner on navigation ──────────────────────────────


def _skills_root() -> Path:
    # helpers.py is src/vesta_browser/helpers.py, so parents[3] is agent/skills/browser/.
    return Path(__file__).resolve().parents[3]


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
    return []


def recipe_banner(url: str) -> str:
    files = recipes_for(url)
    if not files:
        return ""
    lines = [f"📝 Recipes for {urlparse(url).hostname}:"]
    for f in files:
        lines.append(f"  - {f}")
    lines.append(f"  Read via: cat {_skills_root()}/<path>")
    return "\n".join(lines)
