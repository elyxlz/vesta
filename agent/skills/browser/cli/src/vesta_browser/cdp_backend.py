"""CDP backend: drive a remote Chrome/Chromium over the Chrome DevTools Protocol,
presenting the exact surface the daemon uses from BidiClient.

Camoufox (the default launch backend) speaks WebDriver BiDi natively; Chrome does
not expose a BiDi endpoint on --remote-debugging-port, it speaks CDP there. So the
`browser connect` path to a user's own Chrome needs CDP. Rather than branch every
helper on backend, this module is a BiDi -> CDP translator: it accepts the same
`send(bidi_method, params)` calls the helpers already emit and maps them to CDP,
normalizing results and events back into BiDi shapes. Helpers, snapshot, and the
daemon never learn which backend they are on. The in-page snapshot walker and ref
machinery are plain JS, so they run over CDP Runtime.evaluate unchanged.

Stealth is not a goal here (that is Camoufox's job); this drives a browser the user
explicitly handed over, so enabling the CDP domains is fine.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import websockets

from .bidi import BidiError

# WebDriver key code points (U+E0xx) -> CDP key event fields, plus the modifier bit.
_KEY_MAP = {
    "": {"key": "Enter", "code": "Enter", "vk": 13, "text": "\r", "mod": 0},
    "": {"key": "Tab", "code": "Tab", "vk": 9, "text": "\t", "mod": 0},
    "": {"key": "Backspace", "code": "Backspace", "vk": 8, "text": "", "mod": 0},
    "": {"key": "Escape", "code": "Escape", "vk": 27, "text": "", "mod": 0},
    "": {"key": "Delete", "code": "Delete", "vk": 46, "text": "", "mod": 0},
    "": {"key": "ArrowLeft", "code": "ArrowLeft", "vk": 37, "text": "", "mod": 0},
    "": {"key": "ArrowUp", "code": "ArrowUp", "vk": 38, "text": "", "mod": 0},
    "": {"key": "ArrowRight", "code": "ArrowRight", "vk": 39, "text": "", "mod": 0},
    "": {"key": "ArrowDown", "code": "ArrowDown", "vk": 40, "text": "", "mod": 0},
    "": {"key": "Home", "code": "Home", "vk": 36, "text": "", "mod": 0},
    "": {"key": "End", "code": "End", "vk": 35, "text": "", "mod": 0},
    "": {"key": "PageUp", "code": "PageUp", "vk": 33, "text": "", "mod": 0},
    "": {"key": "PageDown", "code": "PageDown", "vk": 34, "text": "", "mod": 0},
    "": {"key": "Alt", "code": "AltLeft", "vk": 18, "text": "", "mod": 1},
    "": {"key": "Control", "code": "ControlLeft", "vk": 17, "text": "", "mod": 2},
    "": {"key": "Meta", "code": "MetaLeft", "vk": 91, "text": "", "mod": 4},
    "": {"key": "Shift", "code": "ShiftLeft", "vk": 16, "text": "", "mod": 8},
}
_CDP_BUTTON = {0: "left", 1: "middle", 2: "right"}
_INTERNAL_PREFIXES = ("devtools://", "chrome://", "chrome-extension://")
_LOAD_TIMEOUT_S = 30.0
_CDP_RESPONSE_TIMEOUT_S = 60.0
_DOMAINS = ("Page", "Runtime", "Log", "DOM")


class _CdpTransport:
    """Raw CDP JSON-RPC over one browser-level websocket (id correlation + events)."""

    def __init__(self) -> None:
        self._ws: websockets.ClientConnection | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._reader: asyncio.Task[None] | None = None
        self._event_cb = None

    async def connect(self, ws_url: str, event_cb) -> None:
        self._event_cb = event_cb
        self._ws = await websockets.connect(ws_url, max_size=None)
        self._reader = asyncio.create_task(self._read_loop())
        self._reader.add_done_callback(self._on_reader_done)

    def _on_reader_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(exc)

    async def _read_loop(self) -> None:
        assert self._ws is not None
        async for raw in self._ws:
            message = json.loads(raw)
            if "id" in message and message["id"] in self._pending:
                future = self._pending.pop(message["id"])
                if future.done():
                    continue
                if "error" in message:
                    future.set_exception(
                        BidiError("cdp error", message["error"]["message"] if "message" in message["error"] else str(message["error"]))
                    )
                else:
                    future.set_result(message["result"] if "result" in message else {})
            elif "method" in message and self._event_cb is not None:
                session_id = message["sessionId"] if "sessionId" in message else None
                await self._event_cb(message["method"], message["params"] if "params" in message else {}, session_id)

    async def send(self, method: str, params: dict | None = None, session_id: str | None = None) -> dict:
        if self._ws is None:
            raise RuntimeError("cdp transport not connected")
        self._next_id += 1
        command_id = self._next_id
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[command_id] = future
        frame: dict = {"id": command_id, "method": method, "params": params or {}}
        if session_id is not None:
            frame["sessionId"] = session_id
        try:
            await self._ws.send(json.dumps(frame))
            return await asyncio.wait_for(future, timeout=_CDP_RESPONSE_TIMEOUT_S)
        except TimeoutError:
            # BidiError, not TimeoutError: the latter is an OSError with an empty str(), which the daemon relays as {"error": ""}.
            raise BidiError("timeout", f"no response to {method!r} within {_CDP_RESPONSE_TIMEOUT_S}s") from None
        finally:
            self._pending.pop(command_id, None)

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
        if self._ws is not None:
            await self._ws.close()


class CdpBackend:
    """Presents BidiClient's surface (connect/new_session/on_event/send/close) over CDP."""

    def __init__(self) -> None:
        self._cdp = _CdpTransport()
        self._sessions: dict[str, str] = {}  # targetId -> CDP flat sessionId
        self._session_targets: dict[str, str] = {}  # sessionId -> targetId
        self._queues: dict[str, asyncio.Queue[dict]] = {}
        self._context = ""

    async def connect(self, ws_url: str) -> None:
        await self._cdp.connect(ws_url, self._on_cdp_event)

    def on_event(self, method: str) -> asyncio.Queue[dict]:
        if method not in self._queues:
            self._queues[method] = asyncio.Queue()
        return self._queues[method]

    async def new_session(self) -> str:
        targets = (await self._cdp.send("Target.getTargets"))["targetInfos"]
        pages = [t for t in targets if t["type"] == "page" and not (t["url"] if "url" in t else "").startswith(_INTERNAL_PREFIXES)]
        target_id = pages[0]["targetId"] if pages else (await self._cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
        await self._session_for(target_id)
        self._context = target_id
        return target_id

    async def close(self) -> None:
        await self._cdp.close()

    # ── Session/target plumbing ───────────────────────────────

    async def _session_for(self, target_id: str) -> str:
        if target_id in self._sessions:
            return self._sessions[target_id]
        try:
            attach = await self._cdp.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        except BidiError as e:
            # Only a refusal means the target is gone. Relabelling a withheld response sends the daemon to re-derive and retry a wedged browser.
            if e.code == "cdp error":
                raise BidiError("no such frame", e.message) from e
            raise
        session_id = attach["sessionId"]
        self._sessions[target_id] = session_id
        self._session_targets[session_id] = target_id
        for domain in _DOMAINS:
            # A domain a given target lacks must not abort the attach.
            with contextlib.suppress(BidiError):
                await self._cdp.send(f"{domain}.enable", {}, session_id)
        return session_id

    # ── BiDi -> CDP command translation ───────────────────────

    async def send(self, method: str, params: dict | None = None) -> dict:
        params = params or {}
        handler = _HANDLERS[method] if method in _HANDLERS else None
        if handler is None:
            raise BidiError("unsupported operation", f"{method} is not supported over the CDP backend")
        return await handler(self, params)

    async def _op_session_new(self, _params: dict) -> dict:
        return {"sessionId": "cdp", "capabilities": {"browserName": "chrome"}}

    async def _op_subscribe(self, _params: dict) -> dict:
        return {}  # domains are enabled per target on attach

    async def _op_get_tree(self, _params: dict) -> dict:
        targets = (await self._cdp.send("Target.getTargets"))["targetInfos"]
        contexts = [{"context": t["targetId"], "url": t["url"] if "url" in t else "", "children": []} for t in targets if t["type"] == "page"]
        return {"contexts": contexts}

    async def _op_navigate(self, params: dict) -> dict:
        session_id = await self._session_for(params["context"])
        await self._cdp.send("Page.navigate", {"url": params["url"]}, session_id)
        if "wait" in params and params["wait"] == "complete":
            await self._wait_for_load(params["context"])
        return {"navigation": None, "url": params["url"]}

    async def _op_reload(self, params: dict) -> dict:
        session_id = await self._session_for(params["context"])
        await self._cdp.send("Page.reload", {}, session_id)
        if "wait" in params and params["wait"] == "complete":
            await self._wait_for_load(params["context"])
        return {}

    async def _op_traverse(self, params: dict) -> dict:
        session_id = await self._session_for(params["context"])
        history = await self._cdp.send("Page.getNavigationHistory", {}, session_id)
        entries = history["entries"]
        index = history["currentIndex"] + params["delta"]
        if 0 <= index < len(entries):
            await self._cdp.send("Page.navigateToHistoryEntry", {"entryId": entries[index]["id"]}, session_id)
        return {}

    async def _op_create(self, _params: dict) -> dict:
        created = await self._cdp.send("Target.createTarget", {"url": "about:blank"})
        return {"context": created["targetId"]}

    async def _op_activate(self, params: dict) -> dict:
        await self._cdp.send("Target.activateTarget", {"targetId": params["context"]})
        return {}

    async def _op_close(self, params: dict) -> dict:
        await self._cdp.send("Target.closeTarget", {"targetId": params["context"]})
        return {}

    async def _op_evaluate(self, params: dict) -> dict:
        target_id = params["target"]["context"]
        session_id = await self._session_for(target_id)
        own_root = "resultOwnership" in params and params["resultOwnership"] == "root"
        cdp_params = {
            "expression": params["expression"],
            "awaitPromise": params["awaitPromise"] if "awaitPromise" in params else False,
            "returnByValue": not own_root,
        }
        result = await self._cdp.send("Runtime.evaluate", cdp_params, session_id)
        if "exceptionDetails" in result:
            detail = result["exceptionDetails"]
            text = detail["text"] if "text" in detail else "exception"
            return {"type": "exception", "exceptionDetails": {"text": text}}
        remote = result["result"]
        if own_root:
            return {"type": "success", "result": {"type": "node", "sharedId": remote["objectId"] if "objectId" in remote else ""}}
        return {"type": "success", "result": _remote_to_bidi(remote)}

    async def _op_perform(self, params: dict) -> dict:
        session_id = await self._session_for(params["context"])
        for source in params["actions"]:
            kind = source["type"]
            if kind == "pointer":
                await self._perform_pointer(source["actions"], session_id)
            elif kind == "key":
                await self._perform_key(source["actions"], session_id)
            elif kind == "wheel":
                await self._perform_wheel(source["actions"], session_id)
        return {}

    async def _op_set_files(self, params: dict) -> dict:
        session_id = await self._session_for(params["context"])
        await self._cdp.send("DOM.setFileInputFiles", {"files": params["files"], "objectId": params["element"]["sharedId"]}, session_id)
        return {}

    async def _op_screenshot(self, params: dict) -> dict:
        session_id = await self._session_for(params["context"])
        fmt = params["format"]
        cdp_params: dict = {"format": "jpeg" if fmt["type"] == "image/jpeg" else "png"}
        if "quality" in fmt:
            cdp_params["quality"] = int(fmt["quality"] * 100)
        if "origin" in params and params["origin"] == "document":
            cdp_params["captureBeyondViewport"] = True
        if "clip" in params:
            clip = params["clip"]
            cdp_params["clip"] = {"x": clip["x"], "y": clip["y"], "width": clip["width"], "height": clip["height"], "scale": 1}
        result = await self._cdp.send("Page.captureScreenshot", cdp_params, session_id)
        return {"data": result["data"]}

    async def _op_print(self, params: dict) -> dict:
        session_id = await self._session_for(params["context"])
        result = await self._cdp.send("Page.printToPDF", {}, session_id)
        return {"data": result["data"]}

    async def _op_set_viewport(self, params: dict) -> dict:
        session_id = await self._session_for(params["context"])
        viewport = params["viewport"]
        await self._cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": viewport["width"], "height": viewport["height"], "deviceScaleFactor": 1, "mobile": False},
            session_id,
        )
        return {}

    async def _op_handle_prompt(self, params: dict) -> dict:
        session_id = await self._session_for(params["context"])
        cdp_params: dict = {"accept": params["accept"] if "accept" in params else True}
        if "userText" in params:
            cdp_params["promptText"] = params["userText"]
        await self._cdp.send("Page.handleJavaScriptDialog", cdp_params, session_id)
        return {}

    # ── Input helpers ─────────────────────────────────────────

    async def _perform_pointer(self, actions: list[dict], session_id: str) -> None:
        x = y = 0
        for action in actions:
            kind = action["type"]
            if kind == "pointerMove":
                x, y = action["x"], action["y"]
                await self._cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, session_id)
            elif kind in ("pointerDown", "pointerUp"):
                button = _CDP_BUTTON[action["button"]] if action["button"] in _CDP_BUTTON else "left"
                event = "mousePressed" if kind == "pointerDown" else "mouseReleased"
                await self._cdp.send("Input.dispatchMouseEvent", {"type": event, "x": x, "y": y, "button": button, "clickCount": 1}, session_id)

    async def _perform_key(self, actions: list[dict], session_id: str) -> None:
        modifiers = 0
        for action in actions:
            value = action["value"]
            info = _KEY_MAP[value] if value in _KEY_MAP else _printable_key(value)
            down = action["type"] == "keyDown"
            if info["mod"]:
                modifiers = modifiers | info["mod"] if down else modifiers & ~info["mod"]
            event: dict = {
                "type": "keyDown" if down else "keyUp",
                "key": info["key"],
                "code": info["code"],
                "windowsVirtualKeyCode": info["vk"],
                "nativeVirtualKeyCode": info["vk"],
                "modifiers": modifiers,
            }
            if down and info["text"]:
                event["text"] = info["text"]
            await self._cdp.send("Input.dispatchKeyEvent", event, session_id)

    async def _perform_wheel(self, actions: list[dict], session_id: str) -> None:
        for action in actions:
            if action["type"] == "scroll":
                await self._cdp.send(
                    "Input.dispatchMouseEvent",
                    {"type": "mouseWheel", "x": action["x"], "y": action["y"], "deltaX": action["deltaX"], "deltaY": action["deltaY"]},
                    session_id,
                )

    async def _wait_for_load(self, target_id: str, timeout_s: float = _LOAD_TIMEOUT_S) -> None:
        session_id = await self._session_for(target_id)
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            result = await self._cdp.send("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True}, session_id)
            if "result" in result and result["result"]["value"] == "complete":
                return
            await asyncio.sleep(0.1)

    # ── CDP -> BiDi event translation ─────────────────────────

    async def _on_cdp_event(self, method: str, params: dict, session_id: str | None) -> None:
        target_id = self._session_targets[session_id] if session_id in self._session_targets else self._context
        translated = _translate_event(method, params, target_id)
        if translated is None:
            return
        bidi_method, bidi_params = translated
        if bidi_method in self._queues:
            await self._queues[bidi_method].put(bidi_params)


def _remote_to_bidi(remote: dict) -> dict:
    """Map a CDP Runtime.RemoteObject (returnByValue) to a BiDi result value."""
    remote_type = remote["type"] if "type" in remote else "undefined"
    if remote_type == "undefined" or "value" not in remote:
        return {"type": "undefined"}
    if remote["value"] is None:
        return {"type": "null"}
    return {"type": remote_type, "value": remote["value"]}


def _printable_key(value: str) -> dict:
    code = f"Key{value.upper()}" if value.isalpha() and len(value) == 1 else ""
    vk = ord(value.upper()) if value.isalpha() and len(value) == 1 else (ord(value[0]) if value else 0)
    return {"key": value, "code": code, "vk": vk, "text": value, "mod": 0}


def _translate_event(method: str, params: dict, target_id: str):
    if method == "Page.loadEventFired":
        return "browsingContext.load", {"context": target_id}
    if method == "Page.domContentEventFired":
        return "browsingContext.domContentLoaded", {"context": target_id}
    if method == "Page.javascriptDialogOpening":
        return "browsingContext.userPromptOpened", {
            "context": target_id,
            "type": params["type"] if "type" in params else "alert",
            "message": params["message"] if "message" in params else "",
            "defaultValue": params["defaultPrompt"] if "defaultPrompt" in params else "",
        }
    if method == "Page.javascriptDialogClosed":
        return "browsingContext.userPromptClosed", {"context": target_id}
    if method in ("Runtime.consoleAPICalled", "Log.entryAdded"):
        return "log.entryAdded", {"context": target_id, "cdp": params}
    return None


_HANDLERS = {
    "session.new": CdpBackend._op_session_new,
    "session.subscribe": CdpBackend._op_subscribe,
    "browsingContext.getTree": CdpBackend._op_get_tree,
    "browsingContext.navigate": CdpBackend._op_navigate,
    "browsingContext.reload": CdpBackend._op_reload,
    "browsingContext.traverseHistory": CdpBackend._op_traverse,
    "browsingContext.create": CdpBackend._op_create,
    "browsingContext.activate": CdpBackend._op_activate,
    "browsingContext.close": CdpBackend._op_close,
    "script.evaluate": CdpBackend._op_evaluate,
    "input.performActions": CdpBackend._op_perform,
    "input.setFiles": CdpBackend._op_set_files,
    "browsingContext.captureScreenshot": CdpBackend._op_screenshot,
    "browsingContext.print": CdpBackend._op_print,
    "browsingContext.setViewport": CdpBackend._op_set_viewport,
    "browsingContext.handleUserPrompt": CdpBackend._op_handle_prompt,
}
