"""The stealth executor: one Camoufox (Playwright Firefox) per session, one process per session.

Runs in the camoufox engine venv. The daemon starts it, speaks JSON lines over stdin/stdout, and
kills the whole process group on a timeout; the profile on disk is what survives. Each exec gets
fresh globals carrying the portable helpers, `page`, `context`, and a `cdp` that refuses.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import functools
import io
import json
import os
import pathlib as pl
import sys
import time
import traceback
import typing as tp

MODIFIER_NAMES = ((1, "Alt"), (2, "Control"), (4, "Meta"), (8, "Shift"))
PAGE_INFO_JS = (
    "() => ({url: location.href, title: document.title, w: innerWidth, h: innerHeight, "
    "sx: scrollX, sy: scrollY, pw: document.documentElement.scrollWidth, ph: document.documentElement.scrollHeight})"
)


class ExecResult(tp.TypedDict):
    stdout: str
    stderr: str
    exit_code: int
    capability_mismatch: str | None
    page: dict[str, str] | None


Payload = ExecResult | dict[str, bool] | dict[str, dict[str, str] | None]
TabTarget = str | dict[str, str]


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


def _resolve(state: WorkerState, target: TabTarget) -> PageLike:
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


def _switch_tab(state: WorkerState, target: TabTarget, activate: bool = False) -> str:
    page = _resolve(state, target)
    _set_page(state, page)
    if activate:
        page.bring_to_front()
    return _tab_id(state, page)


def _close_tab(state: WorkerState, target: TabTarget | None = None) -> None:
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


def _settles(action: tp.Callable[[], None]) -> bool:
    """Whether a Playwright wait finishes; its own TimeoutError subclass is the False answer."""
    try:
        action()
    except Exception:
        return False
    return True


def _wait_for_load(state: WorkerState, timeout: float = 15.0) -> bool:
    return _settles(functools.partial(state.page.wait_for_load_state, "load", timeout=timeout * 1000))


def _wait_for_element(state: WorkerState, selector: str, timeout: float = 10.0, visible: bool = False) -> bool:
    return _settles(
        functools.partial(state.page.wait_for_selector, selector, state="visible" if visible else "attached", timeout=timeout * 1000)
    )


def _wait_for_network_idle(state: WorkerState, timeout: float = 10.0, idle_ms: int = 500) -> bool:
    return _settles(functools.partial(state.page.wait_for_load_state, "networkidle", timeout=timeout * 1000))


def _capture_screenshot(state: WorkerState, path: str | None = None, full: bool = False, max_dim: int | None = None) -> str:
    state.shots += 1
    target = pl.Path(path) if path else state.artifacts / f"shot-{state.shots}.png"
    state.page.screenshot(path=str(target), full_page=full)
    return str(target)


def _upload_file(state: WorkerState, selector: str, path: str) -> None:
    state.page.set_input_files(selector, path)


def _cdp(*_args: object, **_kwargs: object) -> tp.NoReturn:
    raise CapabilityMismatchError("cdp")


# The portable helpers that take the worker state first; `wait` alone needs none of it.
HELPERS: dict[str, tp.Callable[..., object]] = {
    "new_tab": _new_tab,
    "goto_url": _goto_url,
    "page_info": _page_info,
    "current_tab": _current_tab,
    "list_tabs": _list_tabs,
    "switch_tab": _switch_tab,
    "close_tab": _close_tab,
    "ensure_real_tab": _ensure_real_tab,
    "click_at_xy": _click_at_xy,
    "type_text": _type_text,
    "fill_input": _fill_input,
    "press_key": _press_key,
    "scroll": _scroll,
    "js": _js,
    "wait_for_load": _wait_for_load,
    "wait_for_element": _wait_for_element,
    "wait_for_network_idle": _wait_for_network_idle,
    "capture_screenshot": _capture_screenshot,
    "upload_file": _upload_file,
}


def build_globals(state: WorkerState) -> dict[str, object]:
    """One binding per portable helper, `state` bound in so the exec'd code sees plain functions."""
    bound = {name: functools.partial(helper, state) for name, helper in HELPERS.items()}
    return {**bound, "wait": _wait, "cdp": _cdp, "context": state.context, "page": state.page, "__builtins__": __builtins__}


def observe(state: WorkerState) -> dict[str, str] | None:
    if state.page is None:
        return None
    try:
        return {"tab_id": _tab_id(state, state.page), "url": state.page.url, "title": state.page.title()}
    except Exception:
        return None


def _exit_status(code: object) -> int:
    """What the interpreter would exit with: None is 0, an int is itself, anything else prints and is 1."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def run_exec(state: WorkerState, code: str) -> ExecResult:
    out, err = io.StringIO(), io.StringIO()
    exit_code, mismatch = 0, None
    state.exec_globals = build_globals(state)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            exec(code, state.exec_globals)
        except CapabilityMismatchError as exc:
            exit_code, mismatch = 1, exc.operation
            print(str(exc), file=sys.stderr)
        except SystemExit as exc:
            # A program that ends itself is a process exit on the standard route; the same here.
            exit_code = _exit_status(exc.code)
        except BaseException:
            exit_code = 1
            traceback.print_exc()
    return {"stdout": out.getvalue(), "stderr": err.getvalue(), "exit_code": exit_code, "capability_mismatch": mismatch, "page": observe(state)}


def emit(channel: tp.TextIO, payload: Payload) -> None:
    channel.write(json.dumps(payload) + "\n")
    channel.flush()


def protocol_channel() -> tp.TextIO:
    """Moves the protocol stream off fd 1 and points fd 1 at stderr.

    Exec'd code that shells out inherits fd 1, so one stray `echo` in a child would otherwise land
    in the middle of a JSON line the daemon is parsing. Redirecting `sys.stdout` cannot help: it
    rebinds a python object, while a child writes to the file descriptor.
    """
    channel = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    return channel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--window", required=True)
    parser.add_argument("--ff-version", type=int, required=True)
    args = parser.parse_args()
    config = json.loads(pl.Path(args.config).read_text())
    channel = protocol_channel()
    from camoufox.addons import DefaultAddons
    from camoufox.sync_api import Camoufox

    # ff_version names the bundle's Firefox major, so the library never consults its own managed
    # install; excluding uBlock Origin keeps it from downloading an addon at launch.
    width, height = args.window.split("x")
    with Camoufox(
        persistent_context=True,
        user_data_dir=args.profile,
        executable_path=args.executable,
        config=config,
        headless=False,
        ff_version=args.ff_version,
        exclude_addons=[DefaultAddons.UBO],
        i_know_what_im_doing=True,
        window=(int(width), int(height)),
    ) as context:
        state = WorkerState(context, pl.Path(args.artifacts))
        _set_page(state, context.pages[0] if context.pages else context.new_page())
        emit(channel, {"ready": True})
        for line in sys.stdin:
            request = json.loads(line)
            if request["op"] == "exec":
                emit(channel, run_exec(state, str(request["code"])))
            elif request["op"] == "observe":
                emit(channel, {"page": observe(state)})
            elif request["op"] == "stop":
                emit(channel, {"stopped": True})
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
