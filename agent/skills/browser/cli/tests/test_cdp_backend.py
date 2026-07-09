"""Unit tests for the BiDi -> CDP translator (the connect-to-Chrome backend).

The full stack over a real Chromium is exercised in the live smoke; here we pin the
translation logic against a recording fake transport so a wrong CDP mapping fails fast.
"""

from __future__ import annotations

import asyncio

import pytest

from vesta_browser import cdp_backend
from vesta_browser.bidi import BidiError
from vesta_browser.cdp_backend import CdpBackend, _printable_key, _remote_to_bidi, _translate_event


class FakeTransport:
    """Records CDP sends and replies from a canned table keyed by method."""

    def __init__(self, replies: dict | None = None) -> None:
        self.calls: list[tuple[str, dict, str | None]] = []
        self.replies = replies or {}

    async def send(self, method: str, params: dict | None = None, session_id: str | None = None) -> dict:
        self.calls.append((method, params or {}, session_id))
        return self.replies[method] if method in self.replies else {}


def _backend(replies: dict | None = None, context: str = "T1") -> CdpBackend:
    backend = CdpBackend()
    backend._cdp = FakeTransport(replies)
    # Preseed the attach so translations don't need a live Target.attachToTarget.
    backend._sessions[context] = "S1"
    backend._session_targets["S1"] = context
    backend._context = context
    return backend


def _cdp_calls(backend: CdpBackend, method: str) -> list[dict]:
    return [params for (name, params, _sid) in backend._cdp.calls if name == method]


# ── Pure translation helpers ──────────────────────────────────


def test_remote_to_bidi_undefined():
    assert _remote_to_bidi({"type": "undefined"}) == {"type": "undefined"}
    assert _remote_to_bidi({}) == {"type": "undefined"}


def test_remote_to_bidi_null():
    assert _remote_to_bidi({"type": "object", "value": None}) == {"type": "null"}


def test_remote_to_bidi_string():
    assert _remote_to_bidi({"type": "string", "value": '{"a":1}'}) == {"type": "string", "value": '{"a":1}'}


def test_printable_key_letter():
    info = _printable_key("a")
    assert info["text"] == "a"
    assert info["code"] == "KeyA"
    assert info["vk"] == ord("A")


def test_key_map_covers_enter_and_modifiers():
    values = list(cdp_backend._KEY_MAP.values())
    assert any(v["key"] == "Enter" and v["vk"] == 13 for v in values)
    assert any(v["key"] == "Control" and v["mod"] == 2 for v in values)
    assert any(v["key"] == "Shift" and v["mod"] == 8 for v in values)


def test_translate_event_load():
    assert _translate_event("Page.loadEventFired", {}, "T9") == ("browsingContext.load", {"context": "T9"})


def test_translate_event_dialog():
    method, params = _translate_event("Page.javascriptDialogOpening", {"type": "confirm", "message": "ok?"}, "T1")
    assert method == "browsingContext.userPromptOpened"
    assert params["type"] == "confirm"
    assert params["message"] == "ok?"


def test_translate_event_unmapped_returns_none():
    assert _translate_event("Network.requestWillBeSent", {}, "T1") is None


# ── Command translation via a recording transport ─────────────


def test_navigate_maps_to_page_navigate():
    backend = _backend()
    asyncio.run(backend.send("browsingContext.navigate", {"context": "T1", "url": "https://x/"}))
    calls = _cdp_calls(backend, "Page.navigate")
    assert calls == [{"url": "https://x/"}]


def test_navigate_wait_complete_polls_ready_state():
    backend = _backend(replies={"Runtime.evaluate": {"result": {"type": "string", "value": "complete"}}})
    asyncio.run(backend.send("browsingContext.navigate", {"context": "T1", "url": "https://x/", "wait": "complete"}))
    assert any(c["expression"] == "document.readyState" for c in _cdp_calls(backend, "Runtime.evaluate"))


def test_evaluate_returns_bidi_success_shape():
    backend = _backend(replies={"Runtime.evaluate": {"result": {"type": "string", "value": '{"ok":1}'}}})
    out = asyncio.run(backend.send("script.evaluate", {"expression": "x", "target": {"context": "T1"}, "awaitPromise": True}))
    assert out == {"type": "success", "result": {"type": "string", "value": '{"ok":1}'}}
    assert _cdp_calls(backend, "Runtime.evaluate")[0]["returnByValue"] is True


def test_evaluate_exception_maps_to_bidi_exception():
    backend = _backend(replies={"Runtime.evaluate": {"result": {}, "exceptionDetails": {"text": "boom"}}})
    out = asyncio.run(backend.send("script.evaluate", {"expression": "bad", "target": {"context": "T1"}}))
    assert out["type"] == "exception"
    assert out["exceptionDetails"]["text"] == "boom"


def test_evaluate_result_ownership_root_returns_node_handle():
    backend = _backend(replies={"Runtime.evaluate": {"result": {"type": "object", "objectId": "OBJ-9"}}})
    out = asyncio.run(backend.send("script.evaluate", {"expression": "el", "target": {"context": "T1"}, "resultOwnership": "root"}))
    assert out == {"type": "success", "result": {"type": "node", "sharedId": "OBJ-9"}}
    assert _cdp_calls(backend, "Runtime.evaluate")[0]["returnByValue"] is False


def test_pointer_actions_map_to_mouse_events():
    backend = _backend()
    actions = [
        {
            "type": "pointer",
            "id": "m",
            "actions": [
                {"type": "pointerMove", "x": 10, "y": 20},
                {"type": "pointerDown", "button": 2},
                {"type": "pointerUp", "button": 2},
            ],
        }
    ]
    asyncio.run(backend.send("input.performActions", {"context": "T1", "actions": actions}))
    mouse = _cdp_calls(backend, "Input.dispatchMouseEvent")
    assert mouse[0] == {"type": "mouseMoved", "x": 10, "y": 20}
    assert mouse[1]["type"] == "mousePressed" and mouse[1]["button"] == "right"
    assert mouse[2]["type"] == "mouseReleased"


def test_key_actions_track_modifiers():
    backend = _backend()
    ctrl = cdp_backend._KEY_MAP  # locate the Control code point
    control_cp = next(k for k, v in ctrl.items() if v["key"] == "Control")
    actions = [
        {
            "type": "key",
            "id": "k",
            "actions": [
                {"type": "keyDown", "value": control_cp},
                {"type": "keyDown", "value": "a"},
                {"type": "keyUp", "value": "a"},
                {"type": "keyUp", "value": control_cp},
            ],
        }
    ]
    asyncio.run(backend.send("input.performActions", {"context": "T1", "actions": actions}))
    keys = _cdp_calls(backend, "Input.dispatchKeyEvent")
    a_down = next(k for k in keys if k["key"] == "a" and k["type"] == "keyDown")
    assert a_down["modifiers"] == 2  # Control held while 'a' pressed


def test_wheel_actions_map_to_mouse_wheel():
    backend = _backend()
    actions = [{"type": "wheel", "id": "w", "actions": [{"type": "scroll", "x": 5, "y": 6, "deltaX": 0, "deltaY": -100}]}]
    asyncio.run(backend.send("input.performActions", {"context": "T1", "actions": actions}))
    wheel = _cdp_calls(backend, "Input.dispatchMouseEvent")[0]
    assert wheel["type"] == "mouseWheel" and wheel["deltaY"] == -100


def test_screenshot_maps_format_and_quality():
    backend = _backend(replies={"Page.captureScreenshot": {"data": "AAA"}})
    out = asyncio.run(
        backend.send(
            "browsingContext.captureScreenshot",
            {"context": "T1", "origin": "document", "format": {"type": "image/jpeg", "quality": 0.5}},
        )
    )
    assert out == {"data": "AAA"}
    call = _cdp_calls(backend, "Page.captureScreenshot")[0]
    assert call["format"] == "jpeg" and call["quality"] == 50 and call["captureBeyondViewport"] is True


def test_get_tree_maps_targets_to_contexts():
    replies = {
        "Target.getTargets": {
            "targetInfos": [
                {"targetId": "P1", "type": "page", "url": "https://a/"},
                {"targetId": "W1", "type": "service_worker", "url": "https://a/sw.js"},
            ]
        }
    }
    backend = _backend(replies)
    out = asyncio.run(backend.send("browsingContext.getTree", {}))
    assert out["contexts"] == [{"context": "P1", "url": "https://a/", "children": []}]


def test_create_returns_context():
    backend = _backend(replies={"Target.createTarget": {"targetId": "NEW"}})
    out = asyncio.run(backend.send("browsingContext.create", {"type": "tab"}))
    assert out == {"context": "NEW"}


def test_handle_prompt_maps_to_cdp():
    backend = _backend()
    asyncio.run(backend.send("browsingContext.handleUserPrompt", {"context": "T1", "accept": True, "userText": "hi"}))
    call = _cdp_calls(backend, "Page.handleJavaScriptDialog")[0]
    assert call["accept"] is True and call["promptText"] == "hi"


def test_set_files_uses_object_id():
    backend = _backend()
    asyncio.run(backend.send("input.setFiles", {"context": "T1", "element": {"sharedId": "OBJ-1"}, "files": ["/tmp/f"]}))
    call = _cdp_calls(backend, "DOM.setFileInputFiles")[0]
    assert call["objectId"] == "OBJ-1" and call["files"] == ["/tmp/f"]


def test_unsupported_method_raises_bidi_error():
    backend = _backend()
    with pytest.raises(BidiError, match="unsupported operation"):
        asyncio.run(backend.send("storage.getCookies", {}))
