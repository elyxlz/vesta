"""The stealth executor: one Camoufox (Playwright Firefox) per session, one process per session.

Runs in the camoufox engine venv. The daemon starts it, speaks JSON lines over stdin/stdout, and
kills the whole process group on a timeout; the profile on disk is what survives. Each exec gets
fresh globals carrying the portable helpers, `page`, `context`, and a `cdp` that refuses.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import pathlib as pl
import sys
import time
import traceback
import typing as tp

PORTABLE_HELPERS: tuple[str, ...] = (
    "new_tab",
    "goto_url",
    "page_info",
    "current_tab",
    "list_tabs",
    "switch_tab",
    "close_tab",
    "ensure_real_tab",
    "click_at_xy",
    "type_text",
    "fill_input",
    "press_key",
    "scroll",
    "js",
    "wait",
    "wait_for_load",
    "wait_for_element",
    "wait_for_network_idle",
    "capture_screenshot",
    "upload_file",
)
MODIFIER_NAMES = ((1, "Alt"), (2, "Control"), (4, "Meta"), (8, "Shift"))
PAGE_INFO_JS = (
    "() => ({url: location.href, title: document.title, w: innerWidth, h: innerHeight, "
    "sx: scrollX, sy: scrollY, pw: document.documentElement.scrollWidth, ph: document.documentElement.scrollHeight})"
)


class MouseLike(tp.Protocol):
    def click(self, x: float, y: float, button: str = ..., click_count: int = ...) -> None: ...
    def move(self, x: float, y: float) -> None: ...
    def wheel(self, dx: float, dy: float) -> None: ...


class KeyboardLike(tp.Protocol):
    def type(self, text: str) -> None: ...
    def press(self, key: str) -> None: ...


class PageLike(tp.Protocol):
    url: str
    mouse: MouseLike
    keyboard: KeyboardLike

    def title(self) -> str: ...
    def goto(self, url: str) -> None: ...
    def evaluate(self, expression: str) -> object: ...
    def fill(self, selector: str, text: str, timeout: float | None = None) -> None: ...
    def type(self, selector: str, text: str) -> None: ...
    def wait_for_load_state(self, state: str, timeout: float) -> None: ...
    def wait_for_selector(self, selector: str, state: str, timeout: float) -> None: ...
    def screenshot(self, path: str, full_page: bool) -> None: ...
    def set_input_files(self, selector: str, path: str) -> None: ...
    def bring_to_front(self) -> None: ...
    def close(self) -> None: ...


class ContextLike(tp.Protocol):
    pages: list[PageLike]

    def new_page(self) -> PageLike: ...


class CapabilityMismatchError(Exception):
    def __init__(self, operation: str) -> None:
        super().__init__(f"{operation}() is unavailable on camoufox; use the portable helpers or the Playwright page object")
        self.operation = operation


@dataclasses.dataclass
class WorkerState:
    """Mutable per-process state the helpers share; the one holder, no methods."""

    context: ContextLike
    artifacts: pl.Path
    tabs: dict[str, PageLike] = dataclasses.field(default_factory=dict)
    page: PageLike | None = None
    exec_globals: dict[str, object] = dataclasses.field(default_factory=dict)
    shots: int = 0


def _tab_id(state: WorkerState, page: PageLike) -> str:
    for tab_id, known in state.tabs.items():
        if known is page:
            return tab_id
    tab_id = f"tab{len(state.tabs) + 1}"
    state.tabs[tab_id] = page
    return tab_id


def _set_page(state: WorkerState, page: PageLike) -> None:
    state.page = page
    state.exec_globals["page"] = page


def _tab(state: WorkerState, page: PageLike) -> dict[str, str]:
    tab_id = _tab_id(state, page)
    return {"targetId": tab_id, "target_id": tab_id, "url": page.url, "title": page.title()}


def _resolve(state: WorkerState, target: object) -> PageLike:
    tab_id = target["target_id"] if isinstance(target, dict) else str(target)
    return state.tabs[tab_id]


def _new_tab(state: WorkerState, url: str = "about:blank") -> str:
    page = state.context.new_page()
    _set_page(state, page)
    page.goto(url)
    return _tab_id(state, page)


def _goto_url(state: WorkerState, url: str) -> dict[str, str]:
    state.page.goto(url)
    return {"url": state.page.url}


def _page_info(state: WorkerState) -> object:
    return state.page.evaluate(PAGE_INFO_JS)


def _current_tab(state: WorkerState) -> dict[str, str]:
    return _tab(state, state.page)


def _list_tabs(state: WorkerState, include_chrome: bool = True) -> list[dict[str, str]]:
    return [_tab(state, page) for page in state.context.pages if include_chrome or not page.url.startswith("about:")]


def _switch_tab(state: WorkerState, target: object, activate: bool = False) -> str:
    page = _resolve(state, target)
    _set_page(state, page)
    if activate:
        page.bring_to_front()
    return _tab_id(state, page)


def _close_tab(state: WorkerState, target: object | None = None) -> None:
    page = state.page if target is None else _resolve(state, target)
    page.close()
    if page is state.page:
        _set_page(state, state.context.pages[-1] if state.context.pages else state.context.new_page())


def _ensure_real_tab(state: WorkerState) -> dict[str, str]:
    if state.page.url.startswith("about:") and len(state.context.pages) > 1:
        _set_page(state, state.context.pages[-1])
    return _current_tab(state)


def _click_at_xy(state: WorkerState, x: float, y: float, button: str = "left", clicks: int = 1) -> None:
    state.page.mouse.click(x, y, button=button, click_count=clicks)


def _type_text(state: WorkerState, text: str) -> None:
    state.page.keyboard.type(text)


def _fill_input(state: WorkerState, selector: str, text: str, clear_first: bool = True, timeout: float = 0.0) -> None:
    if clear_first:
        state.page.fill(selector, text, timeout=timeout * 1000 if timeout else None)
    else:
        state.page.type(selector, text)


def _press_key(state: WorkerState, key: str, modifiers: int = 0) -> None:
    prefix = "".join(f"{name}+" for bit, name in MODIFIER_NAMES if modifiers & bit)
    state.page.keyboard.press(prefix + key)


def _scroll(state: WorkerState, x: float, y: float, dy: float = -300, dx: float = 0) -> None:
    state.page.mouse.move(x, y)
    state.page.mouse.wheel(dx, dy)


def _js(state: WorkerState, expression: str, target_id: str | None = None) -> object:
    page = state.page if target_id is None else state.tabs[target_id]
    return page.evaluate(expression)


def _wait(seconds: float = 1.0) -> None:
    time.sleep(seconds)


def _wait_for_load(state: WorkerState, timeout: float = 15.0) -> bool:
    try:
        state.page.wait_for_load_state("load", timeout=timeout * 1000)
    except Exception:  # Playwright raises its own TimeoutError subclass
        return False
    return True


def _wait_for_element(state: WorkerState, selector: str, timeout: float = 10.0, visible: bool = False) -> bool:
    try:
        state.page.wait_for_selector(selector, state="visible" if visible else "attached", timeout=timeout * 1000)
    except Exception:
        return False
    return True


def _wait_for_network_idle(state: WorkerState, timeout: float = 10.0, idle_ms: int = 500) -> bool:
    try:
        state.page.wait_for_load_state("networkidle", timeout=timeout * 1000)
    except Exception:
        return False
    return True


def _capture_screenshot(state: WorkerState, path: str | None = None, full: bool = False, max_dim: int | None = None) -> str:
    state.shots += 1
    target = pl.Path(path) if path else state.artifacts / f"shot-{state.shots}.png"
    state.page.screenshot(path=str(target), full_page=full)
    return str(target)


def _upload_file(state: WorkerState, selector: str, path: str) -> None:
    state.page.set_input_files(selector, path)


def _cdp(*_args: object, **_kwargs: object) -> tp.NoReturn:
    raise CapabilityMismatchError("cdp")


def build_globals(state: WorkerState) -> dict[str, object]:
    """One binding per portable helper, `state` closed over so the exec'd code sees plain functions."""
    bound: dict[str, tp.Callable[..., object]] = {
        "new_tab": lambda *a, **kw: _new_tab(state, *a, **kw),
        "goto_url": lambda *a, **kw: _goto_url(state, *a, **kw),
        "page_info": lambda *a, **kw: _page_info(state, *a, **kw),
        "current_tab": lambda *a, **kw: _current_tab(state, *a, **kw),
        "list_tabs": lambda *a, **kw: _list_tabs(state, *a, **kw),
        "switch_tab": lambda *a, **kw: _switch_tab(state, *a, **kw),
        "close_tab": lambda *a, **kw: _close_tab(state, *a, **kw),
        "ensure_real_tab": lambda *a, **kw: _ensure_real_tab(state, *a, **kw),
        "click_at_xy": lambda *a, **kw: _click_at_xy(state, *a, **kw),
        "type_text": lambda *a, **kw: _type_text(state, *a, **kw),
        "fill_input": lambda *a, **kw: _fill_input(state, *a, **kw),
        "press_key": lambda *a, **kw: _press_key(state, *a, **kw),
        "scroll": lambda *a, **kw: _scroll(state, *a, **kw),
        "js": lambda *a, **kw: _js(state, *a, **kw),
        "wait": _wait,
        "wait_for_load": lambda *a, **kw: _wait_for_load(state, *a, **kw),
        "wait_for_element": lambda *a, **kw: _wait_for_element(state, *a, **kw),
        "wait_for_network_idle": lambda *a, **kw: _wait_for_network_idle(state, *a, **kw),
        "capture_screenshot": lambda *a, **kw: _capture_screenshot(state, *a, **kw),
        "upload_file": lambda *a, **kw: _upload_file(state, *a, **kw),
    }
    return {**bound, "cdp": _cdp, "context": state.context, "page": state.page, "__builtins__": __builtins__}


def observe(state: WorkerState) -> dict[str, str] | None:
    if state.page is None:
        return None
    try:
        return {"tab_id": _tab_id(state, state.page), "url": state.page.url, "title": state.page.title()}
    except Exception:
        return None


def run_exec(state: WorkerState, code: str) -> dict[str, object]:
    out, err = io.StringIO(), io.StringIO()
    exit_code, mismatch = 0, None
    state.exec_globals = build_globals(state)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            exec(code, state.exec_globals)
        except CapabilityMismatchError as exc:
            exit_code, mismatch = 1, exc.operation
            print(str(exc), file=sys.stderr)
        except BaseException:
            exit_code = 1
            traceback.print_exc()
    return {"stdout": out.getvalue(), "stderr": err.getvalue(), "exit_code": exit_code, "capability_mismatch": mismatch, "page": observe(state)}


def emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    config = json.loads(pl.Path(args.config).read_text())
    from camoufox.sync_api import Camoufox

    options: dict[str, object] = {
        "persistent_context": True,
        "user_data_dir": args.profile,
        "executable_path": args.executable,
        "config": config,
        "headless": not args.headed,
        "i_know_what_im_doing": True,
    }
    with Camoufox(**options) as context:
        state = WorkerState(context, pl.Path(args.artifacts))
        _set_page(state, context.pages[0] if context.pages else context.new_page())
        emit({"ready": True})
        for line in sys.stdin:
            request = json.loads(line)
            if request["op"] == "exec":
                emit(run_exec(state, str(request["code"])))
            elif request["op"] == "observe":
                emit({"page": observe(state)})
            elif request["op"] == "stop":
                emit({"stopped": True})
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
