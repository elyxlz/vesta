"""The wire contract between the browser CLI, the daemon, and every internal caller.

One request line in, one result line out. Every result has the same shape, every error the same
five fields, and every closed set (codes, phases, states, helpers) is a constant here so the CLI,
the daemon, the engines, and the tests read one owner.
"""

from __future__ import annotations

import datetime as dt
import re
import typing as tp

PROTOCOL_VERSION = 1
SCHEMA = "browser.result.v1"
CODE_MAX_BYTES = 256 * 1024
REQUEST_MAX_BYTES = 512 * 1024
STDOUT_CAP_BYTES = 256 * 1024
STDERR_CAP_BYTES = 16 * 1024
EXEC_TIMEOUT_DEFAULT_SECS = 120
EXEC_TIMEOUT_MIN_SECS = 5
EXEC_TIMEOUT_MAX_SECS = 600
SESSION_IDLE_STOP_SECS = 1800
ARTIFACT_MAX_BYTES = 16 * 1024 * 1024
ARTIFACT_RETENTION_DAYS = 7
# Browser Harness validates BU_NAME as [A-Za-z0-9_-]{1,64}; our names are a subset of that.
SESSION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULT_SESSION = "default"

Mode = tp.Literal["standard", "stealth"]
Engine = tp.Literal["chromium", "camoufox"]
SessionState = tp.Literal["starting", "ready", "busy", "handed_over", "stopped"]
Op = tp.Literal[
    "exec",
    "cancel",
    "status",
    "doctor",
    "engines",
    "sessions",
    "session_stop",
    "stop_all",
    "handover_start",
    "handover_status",
    "handover_stop",
]

ENGINE_FOR_MODE: dict[Mode, Engine] = {"standard": "chromium", "stealth": "camoufox"}
PROTOCOL_FOR_ENGINE: dict[Engine, str] = {"chromium": "cdp", "camoufox": "playwright-firefox"}
PORTABLE_API = "portable-v1"
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
EXTENSIONS_FOR_ENGINE: dict[Engine, list[str]] = {"chromium": ["browser-harness", "cdp"], "camoufox": ["playwright-page"]}

ERROR_CODES = frozenset(
    {
        "invalid_request",
        "session_engine_conflict",
        "engine_unavailable",
        "engine_capability_mismatch",
        "execution_failed",
        "timed_out",
        "cancelled",
        "handover_in_use",
        "handover_failed",
        "daemon_down",
    }
)
PHASES = frozenset({"validation", "routing", "launch", "execution", "observation", "handover", "cleanup"})


class Error(tp.TypedDict):
    code: str
    phase: str
    message: str
    retryable: bool
    suggested_action: str


class SessionInfo(tp.TypedDict):
    name: str
    mode: Mode
    engine: Engine
    protocol: str
    state: SessionState


class PageInfo(tp.TypedDict, total=False):
    state: tp.Literal["ready", "unavailable"]
    tab_id: str
    url: str
    title: str
    observed_at: str


class Output(tp.TypedDict):
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int


class Artifact(tp.TypedDict):
    kind: str
    path: str
    mime_type: str
    bytes: int
    captured_at: str


JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


class Result(tp.TypedDict):
    schema: str
    ok: bool
    request_id: str
    op: str
    session: SessionInfo | None
    page: PageInfo | None
    output: Output | None
    artifacts: list[Artifact]
    warnings: list[str]
    error: Error | None
    data: JsonValue


class BrowserError(Exception):
    """A failure the daemon can name. Carries the wire error so a handler builds the result directly."""

    def __init__(self, err: Error) -> None:
        super().__init__(err["message"])
        self.err = err


def error(code: str, phase: str, message: str, *, retryable: bool, suggested_action: str) -> Error:
    if code not in ERROR_CODES:
        raise ValueError(f"unknown error code {code!r}")
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}")
    return {"code": code, "phase": phase, "message": message, "retryable": retryable, "suggested_action": suggested_action}


def session_info(name: str, mode: Mode, engine: Engine, state: SessionState) -> SessionInfo:
    return {"name": name, "mode": mode, "engine": engine, "protocol": PROTOCOL_FOR_ENGINE[engine], "state": state}


def page_unavailable() -> PageInfo:
    return {"state": "unavailable"}


def result(
    *,
    request_id: str,
    op: str,
    ok: bool,
    session: SessionInfo | None = None,
    page: PageInfo | None = None,
    output: Output | None = None,
    artifacts: tp.Iterable[Artifact] = (),
    warnings: tp.Iterable[str] = (),
    err: Error | None = None,
    data: JsonValue = None,
) -> Result:
    return {
        "schema": SCHEMA,
        "ok": ok,
        "request_id": request_id,
        "op": op,
        "session": session,
        "page": page,
        "output": output,
        "artifacts": list(artifacts),
        "warnings": list(warnings),
        "error": err,
        "data": data,
    }


def truncate(text: str, cap: int) -> tuple[str, bool]:
    """Cut text to at most `cap` UTF-8 bytes, on a character boundary. Returns (text, cut)."""
    raw = text.encode()
    if len(raw) <= cap:
        return text, False
    return raw[:cap].decode(errors="ignore"), True


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
