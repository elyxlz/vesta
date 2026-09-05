# Browser Daemon (PR 1: runtime, engines, CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the browser skill's runtime with one per-agent daemon that runs Vesta's Python programs in Chromium (browser-use + Browser Harness over CDP) or Camoufox (Playwright Firefox), behind a thin `browser` CLI that follows the repo daemon contract.

**Architecture:** `cli/` is a stdlib-only uv project holding the CLI, the daemon (`browser serve`), the session table, the two engine supervisors, artifacts, and doctor. Two locked engine venvs live under `engines/` and are executed by absolute path. Every command sends one JSON line over a 0600 unix socket and prints one JSON line. Handover (PR 2) and the caller/skill rewrite (PR 3) build on this; the three PRs release together.

**Tech Stack:** Python 3.11+ stdlib (asyncio, argparse, json), uv, browser-use 0.13.10 (browser-harness 0.1.13), camoufox 0.5.6b1 + playwright<1.63, Debian `chromium`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-browser-daemon-design.md`

## Global Constraints

- Python under `agent/`: functions plus dataclasses/TypedDicts, no classes with methods, no `getattr`/`hasattr`/dict `.get()`, no `tp.Any`, no `# type: ignore`/`# noqa`, line length 144, `uv run` never bare `python`, `%`-style logging.
- Async: no blocking calls in coroutines; every `create_task` kept in a set; cleanup re-raises `CancelledError`.
- Comments: max 8 lines per block; no `TODO`/`FIXME`/`XXX`/`TEMPORARY`; transitional code carries `LEGACY(remove-when: <condition>)`.
- Every skill command prints one JSON line: success on stdout exit 0, failure on stderr exit 1 (`scripts/check-conventions.py` fails an indented `json.dumps`).
- Daemon contract: `browser daemon start|stop|restart|status`, records `~/agent/data/daemons/browser.pid` as `<pid> <starttime>`, log `~/agent/logs/browser.log`, `DAEMON_READY_TIMEOUT_SECS` default 120, `DAEMON_STOP_TIMEOUT_SECS` default 15, `"port": null`, child launched with `PYTHONUNBUFFERED=1`, claim writes the full record.
- Naming: the live agent is "Vesta"; never a pronoun for Vesta; no spaced dashes in prose; "agent" not "box".
- Constants from the spec, verbatim: `PROTOCOL_VERSION = 1`, `SCHEMA = "browser.result.v1"`, `CODE_MAX_BYTES = 256 * 1024`, `REQUEST_MAX_BYTES = 512 * 1024`, `STDOUT_CAP_BYTES = 256 * 1024`, `STDERR_CAP_BYTES = 16 * 1024`, `EXEC_TIMEOUT_DEFAULT_SECS = 120`, `EXEC_TIMEOUT_MIN_SECS = 5`, `EXEC_TIMEOUT_MAX_SECS = 600`, `SESSION_IDLE_STOP_SECS = 1800`, `ARTIFACT_MAX_BYTES = 16 * 1024 * 1024`, `ARTIFACT_RETENTION_DAYS = 7`, session name `^[a-z0-9][a-z0-9_-]{0,63}$`.
- Paths: socket `~/agent/data/browser/browser.sock`, profiles `~/agent/data/browser/profiles/<engine>/<session>/`, scratch `~/agent/data/browser/sessions/<session>/`, artifacts `~/agent/data/browser/artifacts/<session>/`, Camoufox `/opt/camoufox/<tag>/`, Chromium `/usr/bin/chromium`.
- Never `uv tool install` the chromium engine project: browser-use ships a console script named `browser` that would shadow ours.
- Work in the worktree `../vesta-wt-browser-spec` on branch `spec/browser-daemon` (rename to `feat/browser-daemon` at the first code commit). Run `cd agent && uv run pytest ../agent/skills/browser/cli/tests` from the skill project: `uv run --project skills/browser/cli pytest skills/browser/cli/tests`.

---

## File structure

```
agent/skills/browser/
  install-engines.sh                       Task 12: apt chromium + camoufox_install.py
  engines/chromium/pyproject.toml, uv.lock Task 1
  engines/camoufox/pyproject.toml, uv.lock Task 1
  engines/camoufox/worker.py               Task 7: stealth executor (runs in the camoufox venv)
  cli/pyproject.toml, uv.lock              Task 2 (stdlib only)
  cli/src/vesta_browser/
    __init__.py
    protocol.py        Task 2: consts, TypedDicts, error/result builders, BrowserError
    runtime_paths.py   Task 2: Paths dataclass, load_paths() from env
    presets.py         kept as is (fingerprint presets)
    camoufox_install.py Task 12: standalone stdlib installer (download, sha256, omni.ja repair)
    lifecycle.py       Task 3: daemon start|stop|restart|status
    serve.py           Task 3 skeleton, Task 9 full: unix-socket server, dispatch, idle sweep, signals
    sessions.py        Task 4: session table
    artifacts.py       Task 5: collection, containment, retention
    chromium.py        Task 6: Chromium runtime + browser-use exec child
    camoufox.py        Task 8: worker supervisor
    doctor.py          Task 10
    cli.py             Task 11
  cli/tests/           one test module per source module, plus tests/fake_camoufox/
agent/tests/test_daemon_contract.py        Task 3: browser row
agent/tests/test_service_exposure.py       Task 2: browser line removed
vestad/Dockerfile                          Task 12
check.sh                                   Task 1: engine lockfile freshness
AGENTS.md, ATTRIBUTION.md                  Task 13
```

Deleted in Task 2: `cli/src/vesta_browser/{admin,bidi,cdp_backend,daemon,handover,helpers,launcher,snapshot}.py`, `cli/src/vesta_browser/vendor/`, every file in `cli/tests/`, `interaction-skills/profile-sync.md`. Kept: `presets.py`, `presets/`, `assets/`, `domain-skills/`, `interaction-skills/` (minus profile-sync), `SKILL.md`, `SETUP.md` (rewritten in PR 3), `ATTRIBUTION.md`.

---

### Task 1: Engine venv projects and lockfile guard

**Files:**
- Create: `agent/skills/browser/engines/chromium/pyproject.toml`, `agent/skills/browser/engines/chromium/uv.lock`
- Create: `agent/skills/browser/engines/camoufox/pyproject.toml`, `agent/skills/browser/engines/camoufox/uv.lock`
- Modify: `check.sh` (guards section near line 218)

**Interfaces:**
- Produces: `engines/chromium/.venv/bin/browser-use` and `engines/camoufox/.venv/bin/python` after `uv sync --frozen --project <dir>`; later tasks resolve those paths through `runtime_paths.Paths`.

- [ ] **Step 1: Write the chromium engine project**

```toml
# agent/skills/browser/engines/chromium/pyproject.toml
[project]
name = "vesta-browser-engine-chromium"
version = "0.1.0"
description = "Locked executor environment for the browser daemon's Chromium route: browser-use CLI over Browser Harness (CDP)."
requires-python = ">=3.11"
dependencies = [
    "browser-use==0.13.10",
]

[tool.uv]
package = false
```

- [ ] **Step 2: Write the camoufox engine project**

```toml
# agent/skills/browser/engines/camoufox/pyproject.toml
[project]
name = "vesta-browser-engine-camoufox"
version = "0.1.0"
description = "Locked executor environment for the browser daemon's Camoufox route: the official Camoufox Python API over Playwright Firefox."
requires-python = ">=3.11"
dependencies = [
    "camoufox==0.5.6b1",
    "playwright<1.63",
]

[tool.uv]
package = false
```

- [ ] **Step 3: Lock both**

Run: `cd agent/skills/browser/engines/chromium && uv lock && cd ../camoufox && uv lock`
Expected: both `uv.lock` files exist; `grep -c 'name = "browser-harness"' chromium/uv.lock` prints 1 and the pinned version is `0.1.13`.

- [ ] **Step 4: Confirm the executors resolve**

Run: `cd agent/skills/browser/engines/chromium && uv sync --frozen && ls .venv/bin/browser-use && cd ../camoufox && uv sync --frozen && .venv/bin/python -c "import camoufox.sync_api, playwright; print('ok')"`
Expected: the browser-use path prints; `ok` prints.

- [ ] **Step 5: Add lockfile freshness to `check.sh guards`**

Find the block that copies `agent/core/uv.lock` to `.before`, runs `uv lock --project agent/core`, and diffs. Directly after it add the same three-step check for each engine project:

```bash
  for engine in agent/skills/browser/engines/chromium agent/skills/browser/engines/camoufox; do
    cp "$engine/uv.lock" "$engine/uv.lock.before"
    uv lock --project "$engine"
    if ! diff -q "$engine/uv.lock.before" "$engine/uv.lock" >/dev/null; then
      mv "$engine/uv.lock.before" "$engine/uv.lock"
      echo "$engine/uv.lock is stale; run: uv lock --project $engine" >&2
      exit 1
    fi
    mv "$engine/uv.lock.before" "$engine/uv.lock"
  done
```

Match the surrounding block's variable names and failure style exactly (read it first).

- [ ] **Step 6: Run the guard**

Run: `./check.sh guards`
Expected: passes (shellcheck included).

- [ ] **Step 7: Commit**

```bash
git checkout -b feat/browser-daemon
git add agent/skills/browser/engines check.sh
git commit -m "feat(skills/browser): locked engine environments for chromium and camoufox"
```

---

### Task 2: Reset `cli/` and define the protocol

**Files:**
- Delete: `agent/skills/browser/cli/src/vesta_browser/{admin,bidi,cdp_backend,daemon,handover,helpers,launcher,snapshot}.py`, `agent/skills/browser/cli/src/vesta_browser/vendor/`, `agent/skills/browser/cli/tests/*` (all), `agent/skills/browser/interaction-skills/profile-sync.md`
- Modify: `agent/skills/browser/cli/pyproject.toml`, `agent/skills/browser/cli/uv.lock`
- Modify: `agent/tests/test_service_exposure.py:25` (remove the browser line)
- Create: `agent/skills/browser/cli/src/vesta_browser/protocol.py`, `runtime_paths.py`
- Test: `agent/skills/browser/cli/tests/test_protocol.py`, `test_runtime_paths.py`

**Interfaces:**
- Produces (protocol.py): consts above; `Mode = tp.Literal["standard", "stealth"]`, `Engine = tp.Literal["chromium", "camoufox"]`, `ENGINE_FOR_MODE: dict[Mode, Engine]`, `PROTOCOL_FOR_ENGINE: dict[Engine, str]`, `PORTABLE_HELPERS: tuple[str, ...]`, `EXTENSIONS_FOR_ENGINE: dict[Engine, list[str]]`; TypedDicts `Error`, `SessionInfo`, `PageInfo`, `Output`, `Artifact`, `Result`; `error(code, phase, message, *, retryable, suggested_action) -> Error`; `result(*, request_id, op, ok, session=None, page=None, output=None, artifacts=(), warnings=(), err=None, data=None) -> Result`; `class BrowserError(Exception)` with `.err: Error`; `truncate(text, cap) -> tuple[str, bool]`; `page_unavailable() -> PageInfo`; `session_info(name, mode, engine, state) -> SessionInfo`.
- Produces (runtime_paths.py): `@dataclass(frozen=True) class Paths` with `root, socket, profiles, sessions, artifacts, daemons_dir, log, notifications, chromium_exe, browser_use_bin, camoufox_python, camoufox_exe, worker_script, presets_dir`; `load_paths(env: Mapping[str, str], home: Path) -> Paths`; env overrides `VESTA_BROWSER_CHROMIUM`, `VESTA_BROWSER_BROWSER_USE`, `VESTA_BROWSER_CAMOUFOX_PYTHON`, `VESTA_BROWSER_CAMOUFOX_EXE`.

- [ ] **Step 1: Delete the old runtime**

```bash
cd agent/skills/browser
git rm -r cli/src/vesta_browser/admin.py cli/src/vesta_browser/bidi.py cli/src/vesta_browser/cdp_backend.py \
  cli/src/vesta_browser/daemon.py cli/src/vesta_browser/handover.py cli/src/vesta_browser/helpers.py \
  cli/src/vesta_browser/launcher.py cli/src/vesta_browser/snapshot.py cli/src/vesta_browser/vendor \
  cli/tests interaction-skills/profile-sync.md
mkdir -p cli/tests && touch cli/tests/__init__.py
```

Leave `cli/src/vesta_browser/__init__.py`, `presets.py`, `presets/`, `cli.py` (Task 11 rewrites it; empty its body to `def main() -> int: return 0` for now so the console script still imports).

- [ ] **Step 2: Rewrite `cli/pyproject.toml`**

```toml
[project]
name = "vesta-browser"
version = "0.2.0"
description = "Browser daemon and CLI for Vesta agents: one owner for sessions, both engines, artifacts, and handover."
readme = {text = "", content-type = "text/plain"}
requires-python = ">=3.11"
dependencies = []

[project.scripts]
browser = "vesta_browser.cli:main"

[dependency-groups]
dev = [
    "pytest>=8.4.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/vesta_browser"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Run: `cd agent/skills/browser/cli && uv lock`

- [ ] **Step 3: Remove the browser line from the public-service pin**

In `agent/tests/test_service_exposure.py` delete the line `"browser/cli/src/vesta_browser/handover.py",  # the handover page opens with no credential`. Run `cd agent && uv run pytest tests/test_service_exposure.py -q`; expected PASS.

- [ ] **Step 4: Write the failing protocol tests**

```python
# agent/skills/browser/cli/tests/test_protocol.py
import pytest

from vesta_browser import protocol as p


def test_error_carries_every_required_field():
    err = p.error("timed_out", "execution", "budget exhausted", retryable=True, suggested_action="raise --timeout")
    assert err == {
        "code": "timed_out",
        "phase": "execution",
        "message": "budget exhausted",
        "retryable": True,
        "suggested_action": "raise --timeout",
    }


def test_error_rejects_unknown_code_and_phase():
    with pytest.raises(ValueError):
        p.error("nope", "execution", "m", retryable=False, suggested_action="s")
    with pytest.raises(ValueError):
        p.error("timed_out", "nope", "m", retryable=False, suggested_action="s")


def test_result_defaults_every_optional_component_explicitly():
    res = p.result(request_id="r1", op="status", ok=True)
    assert res["schema"] == p.SCHEMA
    assert res["session"] is None and res["page"] is None and res["output"] is None
    assert res["artifacts"] == [] and res["warnings"] == [] and res["error"] is None and res["data"] is None


def test_failed_result_keeps_verified_context():
    err = p.error("execution_failed", "execution", "boom", retryable=False, suggested_action="fix the code")
    session = p.session_info("research", "standard", "chromium", "ready")
    res = p.result(request_id="r1", op="exec", ok=False, session=session, page=p.page_unavailable(), err=err)
    assert res["ok"] is False and res["error"] == err
    assert res["session"]["engine"] == "chromium" and res["session"]["protocol"] == "cdp"
    assert res["page"] == {"state": "unavailable"}


def test_truncate_reports_whether_it_cut():
    assert p.truncate("abc", 10) == ("abc", False)
    text, cut = p.truncate("x" * 20, 10)
    assert cut is True and len(text.encode()) <= 10


def test_mode_engine_tables_agree():
    assert p.ENGINE_FOR_MODE == {"standard": "chromium", "stealth": "camoufox"}
    assert p.PROTOCOL_FOR_ENGINE == {"chromium": "cdp", "camoufox": "playwright-firefox"}
    assert "cdp" in p.EXTENSIONS_FOR_ENGINE["chromium"] and "playwright-page" in p.EXTENSIONS_FOR_ENGINE["camoufox"]


def test_session_name_pattern():
    assert p.SESSION_NAME_RE.match("default")
    assert p.SESSION_NAME_RE.match("microsoft-alice_example")
    assert not p.SESSION_NAME_RE.match("Has.Dot")
    assert not p.SESSION_NAME_RE.match("-lead")
    assert not p.SESSION_NAME_RE.match("a" * 65)
```

- [ ] **Step 5: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_protocol.py -q`
Expected: FAIL with `ModuleNotFoundError: vesta_browser.protocol`.

- [ ] **Step 6: Write `protocol.py`**

```python
"""The wire contract between the browser CLI, the daemon, and every internal caller.

One request line in, one result line out. Every result has the same shape, every error the same
five fields, and every closed set (codes, phases, states, helpers) is a constant here so the CLI,
the daemon, the engines, and the tests read one owner.
"""

from __future__ import annotations

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
    "exec", "cancel", "status", "doctor", "engines", "sessions", "session_stop", "stop_all",
    "handover_start", "handover_status", "handover_stop",
]

ENGINE_FOR_MODE: dict[Mode, Engine] = {"standard": "chromium", "stealth": "camoufox"}
PROTOCOL_FOR_ENGINE: dict[Engine, str] = {"chromium": "cdp", "camoufox": "playwright-firefox"}
PORTABLE_API = "portable-v1"
PORTABLE_HELPERS: tuple[str, ...] = (
    "new_tab", "goto_url", "page_info",
    "current_tab", "list_tabs", "switch_tab", "close_tab", "ensure_real_tab",
    "click_at_xy", "type_text", "fill_input", "press_key", "scroll",
    "js", "wait", "wait_for_load", "wait_for_element", "wait_for_network_idle",
    "capture_screenshot", "upload_file",
)
EXTENSIONS_FOR_ENGINE: dict[Engine, list[str]] = {"chromium": ["browser-harness", "cdp"], "camoufox": ["playwright-page"]}

ERROR_CODES = frozenset({
    "invalid_request", "session_engine_conflict", "engine_unavailable", "engine_capability_mismatch",
    "execution_failed", "timed_out", "cancelled", "handover_in_use", "handover_failed", "daemon_down",
})
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


JsonValue = tp.Union[str, int, float, bool, None, list["JsonValue"], dict[str, "JsonValue"]]


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
        "schema": SCHEMA, "ok": ok, "request_id": request_id, "op": op, "session": session, "page": page,
        "output": output, "artifacts": list(artifacts), "warnings": list(warnings), "error": err, "data": data,
    }


def truncate(text: str, cap: int) -> tuple[str, bool]:
    """Cut text to at most `cap` UTF-8 bytes, on a character boundary. Returns (text, cut)."""
    raw = text.encode()
    if len(raw) <= cap:
        return text, False
    return raw[:cap].decode(errors="ignore"), True
```

- [ ] **Step 7: Write the failing `runtime_paths` test**

```python
# agent/skills/browser/cli/tests/test_runtime_paths.py
import pathlib as pl

from vesta_browser.runtime_paths import load_paths


def test_defaults_hang_off_home_and_the_skill_dir(tmp_path):
    paths = load_paths({}, tmp_path)
    assert paths.socket == tmp_path / "agent/data/browser/browser.sock"
    assert paths.profiles == tmp_path / "agent/data/browser/profiles"
    assert paths.sessions == tmp_path / "agent/data/browser/sessions"
    assert paths.artifacts == tmp_path / "agent/data/browser/artifacts"
    assert paths.daemons_dir == tmp_path / "agent/data/daemons"
    assert paths.log == tmp_path / "agent/logs/browser.log"
    assert paths.notifications == tmp_path / "agent/notifications"
    assert paths.chromium_exe == pl.Path("/usr/bin/chromium")
    assert paths.browser_use_bin.name == "browser-use" and "engines/chromium/.venv/bin" in str(paths.browser_use_bin)
    assert paths.camoufox_python.name == "python" and "engines/camoufox/.venv/bin" in str(paths.camoufox_python)
    assert paths.worker_script.name == "worker.py" and paths.worker_script.parent.name == "camoufox"
    assert str(paths.camoufox_exe).startswith("/opt/camoufox/") and paths.camoufox_exe.name == "camoufox"
    assert paths.presets_dir.is_dir()


def test_env_overrides_every_binary(tmp_path):
    env = {
        "VESTA_BROWSER_CHROMIUM": "/x/chromium",
        "VESTA_BROWSER_BROWSER_USE": "/x/browser-use",
        "VESTA_BROWSER_CAMOUFOX_PYTHON": "/x/python",
        "VESTA_BROWSER_CAMOUFOX_EXE": "/x/camoufox",
    }
    paths = load_paths(env, tmp_path)
    assert (paths.chromium_exe, paths.browser_use_bin, paths.camoufox_python, paths.camoufox_exe) == (
        pl.Path("/x/chromium"), pl.Path("/x/browser-use"), pl.Path("/x/python"), pl.Path("/x/camoufox"),
    )
```

- [ ] **Step 8: Write `runtime_paths.py`**

```python
"""Every filesystem location the daemon touches, resolved once at startup and passed down.

Tests inject binaries through the four VESTA_BROWSER_* overrides; production reads the defaults.
"""

from __future__ import annotations

import dataclasses
import pathlib as pl
import typing as tp

SKILL_DIR = pl.Path(__file__).resolve().parents[3]
ENGINES_DIR = SKILL_DIR / "engines"
CAMOUFOX_INSTALL_ROOT = pl.Path("/opt/camoufox")
# LEGACY(remove-when: camoufox_install.CAMOUFOX_RELEASE_TAG moves): duplicated here rather than
# imported, because camoufox_install.py runs standalone under the system python and must not
# import the package; Task 12 asserts the two values agree.
CAMOUFOX_RELEASE_TAG = "v150.0.2-beta.25"


@dataclasses.dataclass(frozen=True)
class Paths:
    root: pl.Path
    socket: pl.Path
    profiles: pl.Path
    sessions: pl.Path
    artifacts: pl.Path
    daemons_dir: pl.Path
    log: pl.Path
    notifications: pl.Path
    chromium_exe: pl.Path
    browser_use_bin: pl.Path
    camoufox_python: pl.Path
    camoufox_exe: pl.Path
    worker_script: pl.Path
    presets_dir: pl.Path


def _override(env: tp.Mapping[str, str], key: str, default: pl.Path) -> pl.Path:
    return pl.Path(env[key]) if key in env else default


def load_paths(env: tp.Mapping[str, str], home: pl.Path) -> Paths:
    root = home / "agent/data/browser"
    return Paths(
        root=root,
        socket=root / "browser.sock",
        profiles=root / "profiles",
        sessions=root / "sessions",
        artifacts=root / "artifacts",
        daemons_dir=home / "agent/data/daemons",
        log=home / "agent/logs/browser.log",
        notifications=home / "agent/notifications",
        chromium_exe=_override(env, "VESTA_BROWSER_CHROMIUM", pl.Path("/usr/bin/chromium")),
        browser_use_bin=_override(env, "VESTA_BROWSER_BROWSER_USE", ENGINES_DIR / "chromium/.venv/bin/browser-use"),
        camoufox_python=_override(env, "VESTA_BROWSER_CAMOUFOX_PYTHON", ENGINES_DIR / "camoufox/.venv/bin/python"),
        camoufox_exe=_override(env, "VESTA_BROWSER_CAMOUFOX_EXE", CAMOUFOX_INSTALL_ROOT / CAMOUFOX_RELEASE_TAG / "camoufox"),
        worker_script=ENGINES_DIR / "camoufox/worker.py",
        presets_dir=SKILL_DIR / "cli/src/vesta_browser/presets",
    )
```

- [ ] **Step 9: Run both test modules**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests -q`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add -A agent/skills/browser agent/tests/test_service_exposure.py
git commit -m "refactor(skills/browser): remove the bidi runtime and define the daemon protocol"
```

---

### Task 3: Daemon lifecycle and the serve skeleton

**Files:**
- Create: `agent/skills/browser/cli/src/vesta_browser/lifecycle.py`, `serve.py` (skeleton: `status`, `engines` ops only), `cli.py` (minimal: `daemon` and `serve` verbs)
- Modify: `agent/tests/test_daemon_contract.py` (add the browser row)
- Test: `agent/skills/browser/cli/tests/test_serve_skeleton.py`, `agent/tests/test_daemon_contract.py`

**Interfaces:**
- Produces (lifecycle.py): `NAME = "browser"`, `daemon_cmd(action: str, paths: Paths) -> int`, `live_pid(paths) -> int | None`, `READY_TIMEOUT_SECS`, `STOP_TIMEOUT_SECS`.
- Produces (serve.py): `@dataclass class State(paths: Paths, table: SessionTable, inflight: dict[str, asyncio.Task[Result]], tasks: set[asyncio.Task[None]], last_error: Error | None)`; `async def serve(paths: Paths) -> int`; `async def handle_request(state, request: dict) -> Result`; `def ping(paths, timeout: float) -> bool` (sync, used by lifecycle readiness and the CLI's `daemon_down` detection); `async def request(paths, payload: dict) -> Result` (async client used by tests).
- Consumes: Task 2's `protocol`, `runtime_paths`. Task 4 replaces the placeholder `SessionTable` import; until then `serve.py` holds `table: None`.

- [ ] **Step 1: Write the failing skeleton test**

```python
# agent/skills/browser/cli/tests/test_serve_skeleton.py
import asyncio
import json

import pytest

from vesta_browser import serve
from vesta_browser.runtime_paths import load_paths


@pytest.fixture
def paths(tmp_path):
    return load_paths({}, tmp_path)


async def _serve_for(paths, coro):
    server_task = asyncio.create_task(serve.serve(paths))
    try:
        for _ in range(100):
            if paths.socket.exists():
                break
            await asyncio.sleep(0.02)
        return await coro
    finally:
        server_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await server_task


def test_status_answers_over_the_socket(paths):
    async def run():
        return await serve.request(paths, {"version": 1, "op": "status", "request_id": "r1"})

    res = asyncio.run(_serve_for(paths, run()))
    assert res["ok"] is True and res["op"] == "status" and res["request_id"] == "r1"
    assert res["data"]["protocol_version"] == 1 and res["data"]["pid"] > 0


def test_unknown_version_and_op_are_invalid_requests(paths):
    async def run():
        bad_version = await serve.request(paths, {"version": 99, "op": "status", "request_id": "r1"})
        bad_op = await serve.request(paths, {"version": 1, "op": "dance", "request_id": "r2"})
        return bad_version, bad_op

    bad_version, bad_op = asyncio.run(_serve_for(paths, run()))
    assert bad_version["ok"] is False and bad_version["error"]["code"] == "invalid_request"
    assert bad_op["ok"] is False and bad_op["error"]["code"] == "invalid_request" and bad_op["error"]["phase"] == "validation"


def test_socket_is_private(paths):
    async def run():
        return oct(paths.socket.stat().st_mode & 0o777)

    assert asyncio.run(_serve_for(paths, run())) == "0o600"


def test_engines_reports_readiness_from_binaries(paths, tmp_path):
    async def run():
        return await serve.request(paths, {"version": 1, "op": "engines", "request_id": "r1"})

    res = asyncio.run(_serve_for(paths, run()))
    routes = res["data"]["routes"]
    assert routes["standard"]["engine"] == "chromium" and routes["standard"]["protocol"] == "cdp"
    assert routes["stealth"]["engine"] == "camoufox" and routes["stealth"]["protocol"] == "playwright-firefox"
    assert routes["standard"]["ready"] is False  # /usr/bin/chromium is not on the test box's path override
    assert res["data"]["portable_helpers"][0] == "new_tab"
    assert res["data"]["profiles_shared_between_engines"] is False


def test_ping_is_false_with_no_daemon(paths):
    assert serve.ping(paths, timeout=0.2) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_serve_skeleton.py -q`
Expected: FAIL, `ModuleNotFoundError: vesta_browser.serve`.

- [ ] **Step 3: Write `serve.py` (skeleton)**

```python
"""The browser daemon: one unix socket, one JSON line per request, one owner for every browser decision.

`browser daemon start` runs `browser serve` detached; nothing else launches this. Handlers return a
`protocol.Result`, and a `BrowserError` raised anywhere inside a handler becomes the failed result
for that request alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime as dt
import json
import logging
import os
import signal
import socket
import sys
import time
import typing as tp

from . import protocol as p
from .runtime_paths import Paths

logger = logging.getLogger(__name__)
IDLE_SWEEP_SECS = 60
CLIENT_TIMEOUT_SECS = 5.0


@dataclasses.dataclass
class State:
    paths: Paths
    inflight: dict[str, asyncio.Task[p.Result]] = dataclasses.field(default_factory=dict)
    tasks: set[asyncio.Task[None]] = dataclasses.field(default_factory=set)
    last_error: p.Error | None = None
    asked_to_stop: bool = False


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _invalid(message: str) -> p.Error:
    return p.error("invalid_request", "validation", message, retryable=False, suggested_action="fix the request and retry")


def routes(paths: Paths) -> dict[str, p.JsonValue]:
    """The mode-to-engine table with readiness read from the binaries on disk."""
    ready = {
        "chromium": paths.chromium_exe.is_file() and paths.browser_use_bin.is_file(),
        "camoufox": paths.camoufox_python.is_file() and paths.camoufox_exe.is_file() and paths.worker_script.is_file(),
    }
    table: dict[str, p.JsonValue] = {}
    for mode, engine in p.ENGINE_FOR_MODE.items():
        table[mode] = {
            "engine": engine,
            "protocol": p.PROTOCOL_FOR_ENGINE[engine],
            "backend": "local",
            "ready": ready[engine],
            "api": {"portable": p.PORTABLE_API, "extensions": list(p.EXTENSIONS_FOR_ENGINE[engine])},
        }
    return {
        "default_mode": "standard",
        "routes": table,
        "portable_helpers": list(p.PORTABLE_HELPERS),
        "profiles_shared_between_engines": False,
    }


async def op_status(state: State, request_id: str) -> p.Result:
    data: p.JsonValue = {"protocol_version": p.PROTOCOL_VERSION, "pid": os.getpid(), "socket": str(state.paths.socket)}
    return p.result(request_id=request_id, op="status", ok=True, data=data)


async def op_engines(state: State, request_id: str) -> p.Result:
    return p.result(request_id=request_id, op="engines", ok=True, data=routes(state.paths))


Handler = tp.Callable[[State, dict[str, p.JsonValue]], tp.Awaitable[p.Result]]


async def handle_request(state: State, request: dict[str, p.JsonValue]) -> p.Result:
    request_id = str(request["request_id"]) if "request_id" in request else ""
    op = str(request["op"]) if "op" in request else ""
    try:
        if "version" not in request or request["version"] != p.PROTOCOL_VERSION:
            raise p.BrowserError(_invalid(f"unsupported protocol version; this daemon speaks {p.PROTOCOL_VERSION}"))
        if op not in HANDLERS:
            raise p.BrowserError(_invalid(f"unknown op {op!r}"))
        return await HANDLERS[op](state, request)
    except p.BrowserError as exc:
        state.last_error = exc.err
        return p.result(request_id=request_id, op=op, ok=False, err=exc.err)


async def _handle_connection(state: State, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = await reader.readline()
    except asyncio.LimitOverrunError:
        line = b""
    try:
        request = json.loads(line) if line else {}
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        response = await handle_request(state, request)
    except ValueError as exc:
        response = p.result(request_id="", op="", ok=False, err=_invalid(f"unreadable request: {exc}"))
    writer.write((json.dumps(response) + "\n").encode())
    with contextlib.suppress(ConnectionError):
        await writer.drain()
    writer.close()


def _write_daemon_died(paths: Paths, reason: str) -> None:
    paths.notifications.mkdir(exist_ok=True)
    notif = {"source": "browser", "type": "daemon_died", "reason": reason, "timestamp": now_iso()}
    filename = f"{int(time.time() * 1e6)}-browser-daemon_died.json"
    tmp = paths.notifications / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif))
    tmp.replace(paths.notifications / filename)


async def serve(paths: Paths) -> int:
    state = State(paths=paths)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.socket.unlink(missing_ok=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def on_signal(signum: int) -> None:
        state.asked_to_stop = signum == signal.SIGTERM
        stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, on_signal, signum)
    old_umask = os.umask(0o077)
    try:
        server = await asyncio.start_unix_server(
            lambda r, w: _handle_connection(state, r, w), path=str(paths.socket), limit=p.REQUEST_MAX_BYTES
        )
    finally:
        os.umask(old_umask)
    logger.info("browser daemon listening on %s", paths.socket)
    try:
        await stop.wait()
    finally:
        server.close()
        await server.wait_closed()
        await shutdown(state)
        paths.socket.unlink(missing_ok=True)
        if not state.asked_to_stop:
            _write_daemon_died(paths, "signal")
    return 0


async def shutdown(state: State) -> None:
    """Stops every session; Task 9 fills this in. The skeleton has nothing to stop."""
    for task in list(state.tasks):
        task.cancel()
    for task in list(state.tasks):
        with contextlib.suppress(asyncio.CancelledError):
            await task


def ping(paths: Paths, timeout: float) -> bool:
    """Sync liveness probe: a daemon that answers `status` is up. Used by lifecycle readiness and the CLI."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(paths.socket))
            sock.sendall(json.dumps({"version": p.PROTOCOL_VERSION, "op": "status", "request_id": "ping"}).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        return bool(data) and json.loads(data)["ok"] is True
    except (OSError, ValueError, KeyError):
        return False


async def request(paths: Paths, payload: dict[str, p.JsonValue]) -> p.Result:
    reader, writer = await asyncio.open_unix_connection(str(paths.socket), limit=p.REQUEST_MAX_BYTES * 4)
    writer.write((json.dumps(payload) + "\n").encode())
    await writer.drain()
    line = await reader.readline()
    writer.close()
    return json.loads(line)


HANDLERS: dict[str, Handler] = {
    "status": lambda state, req: op_status(state, str(req["request_id"])),
    "engines": lambda state, req: op_engines(state, str(req["request_id"])),
}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    return asyncio.run(serve(load_paths(os.environ, pl.Path.home())))
```

Imports at the top must also include `import pathlib as pl` and `from .runtime_paths import Paths, load_paths`.

- [ ] **Step 4: Run the skeleton tests**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_serve_skeleton.py -q`
Expected: PASS.

- [ ] **Step 5: Write `lifecycle.py`**

Port `agent/skills/tasks/cli/src/tasks_cli/daemon.py` with these differences: `NAME = "browser"`, no port record and no `register-service`, readiness is `serve.ping(paths, PROBE_TIMEOUT_SECS)`, records and log paths come from `Paths`, the child is `[sys.argv[0], "serve"]` with `PYTHONUNBUFFERED=1` and `start_new_session=True`, and `_status` prints `{"running": running, "port": None}`. Keep `_starttime`, `_record`, `live_pid`, `_claim`, `_claim_start` (with `handle.write(_record(pid))`), `_abandon`, `_await_ready`, `_await_gone`, `_stop`, `daemon_cmd` verbatim in shape; every function takes `paths: Paths` explicitly instead of module-level `PIDFILE`/`LOG`. Signature: `def daemon_cmd(action: str, paths: Paths) -> int`. `USAGE = "Usage: browser daemon <start|stop|restart|status>"`.

- [ ] **Step 6: Write the minimal `cli.py`**

```python
"""The `browser` command: a thin client. Task 11 adds every RPC verb; this stage carries the daemon verbs only."""

from __future__ import annotations

import os
import pathlib as pl
import sys

from . import lifecycle, serve
from .runtime_paths import load_paths


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    paths = load_paths(os.environ, pl.Path.home())
    if args and args[0] == "daemon":
        return lifecycle.daemon_cmd(args[1] if len(args) > 1 else "", paths)
    if args and args[0] == "serve":
        return serve.main()
    print(lifecycle.USAGE, file=sys.stderr)
    return 1
```

- [ ] **Step 7: Add the contract row**

In `agent/tests/test_daemon_contract.py`, after the `google` row, add:

```python
    Daemon(
        command=["uv", "run", "--project", str(SKILLS_DIR / "browser/cli"), "browser"],
        name="browser",
        serves_port=False,
        emits_daemon_died=True,
    ),
```

- [ ] **Step 8: Run the contract suite for browser**

Run: `cd agent && uv run pytest tests/test_daemon_contract.py -k browser -q`
Expected: every non-skipped test PASSES (idempotent start, race, reused pid, stop, restart, deliberate stop silent, SIGINT reported, usage). If `test_a_death_nobody_asked_for_is_reported` fails, check that `_write_daemon_died` runs on SIGINT and that `paths.notifications` is `$HOME/agent/notifications`.

- [ ] **Step 9: Run the source-scan tests**

Run: `cd agent && uv run pytest tests/test_daemon_contract.py -k "unbuffered or bare_pid" -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add agent/skills/browser/cli agent/tests/test_daemon_contract.py
git commit -m "feat(skills/browser): daemon lifecycle and socket server skeleton"
```

---

### Task 4: Session table

**Files:**
- Create: `agent/skills/browser/cli/src/vesta_browser/sessions.py`
- Test: `agent/skills/browser/cli/tests/test_sessions.py`

**Interfaces:**
- Produces: `@dataclass class Session(name: str, mode: Mode, engine: Engine, state: SessionState, profile_dir: Path, scratch_dir: Path, artifact_dir: Path, last_activity: float, runtime: object | None = None, request_id: str | None = None)` where `runtime` is engine-owned (`chromium.ChromiumRuntime` or `camoufox.CamoufoxRuntime`, typed as `EngineRuntime = tp.Union[...]` after Tasks 6 and 8; use `tp.Union["ChromiumRuntime", "CamoufoxRuntime"] | None` with `TYPE_CHECKING` imports then).
- `@dataclass class SessionTable(paths: Paths, sessions: dict[str, Session], clock: Callable[[], float])`.
- `load_table(paths, clock=time.monotonic) -> SessionTable` (rebuilds `stopped` sessions from `profiles/<engine>/<name>` dirs).
- `resolve_session(table, name, mode: Mode | None) -> Session` (validates, creates dirs, pins, raises `BrowserError`).
- `touch(table, session) -> None`; `idle_sessions(table) -> list[Session]`; `info(session) -> SessionInfo`; `mark(session, state) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# agent/skills/browser/cli/tests/test_sessions.py
import pytest

from vesta_browser import protocol as p
from vesta_browser import sessions as s
from vesta_browser.runtime_paths import load_paths


@pytest.fixture
def table(tmp_path):
    clock = {"now": 1000.0}
    return s.load_table(load_paths({}, tmp_path), clock=lambda: clock["now"]), clock


def test_new_session_pins_the_requested_mode_and_creates_its_dirs(table):
    table, _ = table
    session = s.resolve_session(table, "research", "stealth")
    assert session.engine == "camoufox" and session.mode == "stealth" and session.state == "stopped"
    assert session.profile_dir.is_dir() and session.profile_dir.parts[-2:] == ("camoufox", "research")
    assert session.scratch_dir.is_dir() and session.artifact_dir.is_dir()


def test_omitted_mode_defaults_to_standard_on_a_new_session(table):
    table, _ = table
    assert s.resolve_session(table, "default", None).engine == "chromium"


def test_omitted_mode_inherits_and_explicit_conflict_fails(table):
    table, _ = table
    s.resolve_session(table, "research", "stealth")
    assert s.resolve_session(table, "research", None).engine == "camoufox"
    with pytest.raises(p.BrowserError) as excinfo:
        s.resolve_session(table, "research", "standard")
    err = excinfo.value.err
    assert err["code"] == "session_engine_conflict" and err["phase"] == "routing"
    assert "camoufox" in err["message"] and "standard" in err["message"]


@pytest.mark.parametrize("name", ["", "Upper", "has.dot", "-lead", "a" * 65, "sp ace"])
def test_bad_names_are_invalid_requests(table, name):
    table, _ = table
    with pytest.raises(p.BrowserError) as excinfo:
        s.resolve_session(table, name, None)
    assert excinfo.value.err["code"] == "invalid_request"


def test_table_rebuilds_stopped_sessions_from_profile_dirs(tmp_path):
    paths = load_paths({}, tmp_path)
    (paths.profiles / "camoufox/microsoft-alice").mkdir(parents=True)
    (paths.profiles / "chromium/default").mkdir(parents=True)
    table = s.load_table(paths)
    assert {n: (x.engine, x.state) for n, x in table.sessions.items()} == {
        "microsoft-alice": ("camoufox", "stopped"),
        "default": ("chromium", "stopped"),
    }


def test_idle_sessions_are_ready_ones_past_the_idle_budget(table):
    table, clock = table
    ready = s.resolve_session(table, "a", None)
    s.mark(ready, "ready")
    busy = s.resolve_session(table, "b", None)
    s.mark(busy, "busy")
    clock["now"] += p.SESSION_IDLE_STOP_SECS + 1
    assert [x.name for x in s.idle_sessions(table)] == ["a"]
    s.touch(table, ready)
    assert s.idle_sessions(table) == []


def test_info_matches_the_wire_shape(table):
    table, _ = table
    session = s.resolve_session(table, "research", "stealth")
    assert s.info(session) == {"name": "research", "mode": "stealth", "engine": "camoufox", "protocol": "playwright-firefox", "state": "stopped"}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_sessions.py -q`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `sessions.py`**

```python
"""The session table: one browser process and one profile per name, engine pinned for life.

A session is known while its profile directory exists, so the table survives a daemon restart as a
set of `stopped` sessions. Engine-specific process handles hang off `Session.runtime`.
"""

from __future__ import annotations

import dataclasses
import pathlib as pl
import time
import typing as tp

from . import protocol as p
from .runtime_paths import Paths

if tp.TYPE_CHECKING:
    from .camoufox import CamoufoxRuntime
    from .chromium import ChromiumRuntime

EngineRuntime = tp.Union["ChromiumRuntime", "CamoufoxRuntime"]
MODE_FOR_ENGINE: dict[p.Engine, p.Mode] = {engine: mode for mode, engine in p.ENGINE_FOR_MODE.items()}


@dataclasses.dataclass
class Session:
    name: str
    mode: p.Mode
    engine: p.Engine
    state: p.SessionState
    profile_dir: pl.Path
    scratch_dir: pl.Path
    artifact_dir: pl.Path
    last_activity: float
    runtime: EngineRuntime | None = None
    request_id: str | None = None


@dataclasses.dataclass
class SessionTable:
    paths: Paths
    sessions: dict[str, Session]
    clock: tp.Callable[[], float]


def _make(paths: Paths, name: str, engine: p.Engine, now: float) -> Session:
    session = Session(
        name=name,
        mode=MODE_FOR_ENGINE[engine],
        engine=engine,
        state="stopped",
        profile_dir=paths.profiles / engine / name,
        scratch_dir=paths.sessions / name,
        artifact_dir=paths.artifacts / name,
        last_activity=now,
    )
    for directory in (session.profile_dir, session.scratch_dir, session.artifact_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return session


def load_table(paths: Paths, clock: tp.Callable[[], float] = time.monotonic) -> SessionTable:
    table = SessionTable(paths=paths, sessions={}, clock=clock)
    for engine in p.ENGINE_FOR_MODE.values():
        engine_dir = paths.profiles / engine
        if not engine_dir.is_dir():
            continue
        for profile in sorted(engine_dir.iterdir()):
            if profile.is_dir() and p.SESSION_NAME_RE.match(profile.name):
                table.sessions[profile.name] = _make(paths, profile.name, engine, clock())
    return table


def resolve_session(table: SessionTable, name: str, mode: p.Mode | None) -> Session:
    if not p.SESSION_NAME_RE.match(name):
        raise p.BrowserError(
            p.error(
                "invalid_request", "validation",
                f"session name {name!r} must match {p.SESSION_NAME_RE.pattern}",
                retryable=False, suggested_action="use lowercase letters, digits, '-' and '_'",
            )
        )
    if name in table.sessions:
        session = table.sessions[name]
        if mode is not None and mode != session.mode:
            raise p.BrowserError(
                p.error(
                    "session_engine_conflict", "routing",
                    f"session {name!r} is pinned to {session.engine} ({session.mode}); requested {mode}",
                    retryable=False, suggested_action="omit the mode to reuse this session, or start a new session name for the other engine",
                )
            )
        return session
    session = _make(table.paths, name, p.ENGINE_FOR_MODE[mode or "standard"], table.clock())
    table.sessions[name] = session
    return session


def touch(table: SessionTable, session: Session) -> None:
    session.last_activity = table.clock()


def mark(session: Session, state: p.SessionState) -> None:
    session.state = state


def idle_sessions(table: SessionTable) -> list[Session]:
    cutoff = table.clock() - p.SESSION_IDLE_STOP_SECS
    return [x for x in table.sessions.values() if x.state == "ready" and x.last_activity < cutoff]


def info(session: Session) -> p.SessionInfo:
    return p.session_info(session.name, session.mode, session.engine, session.state)
```

- [ ] **Step 4: Run the tests**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_sessions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/skills/browser/cli
git commit -m "feat(skills/browser): session table with engine pinning and idle detection"
```

---

### Task 5: Artifacts

**Files:**
- Create: `agent/skills/browser/cli/src/vesta_browser/artifacts.py`
- Test: `agent/skills/browser/cli/tests/test_artifacts.py`

**Interfaces:**
- Produces: `collect(session: Session, stdout: str, started_at: float, now: Callable[[], str]) -> tuple[list[Artifact], list[str]]` (artifacts, warnings); `prune(paths: Paths, now: float = time.time()) -> int` (files removed).
- Consumes: `sessions.Session` (`scratch_dir`, `artifact_dir`), `protocol.Artifact`, `ARTIFACT_MAX_BYTES`, `ARTIFACT_RETENTION_DAYS`.

- [ ] **Step 1: Write the failing tests**

```python
# agent/skills/browser/cli/tests/test_artifacts.py
import os
import time

import pytest

from vesta_browser import artifacts as a
from vesta_browser import sessions as s
from vesta_browser.runtime_paths import load_paths

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture
def session(tmp_path):
    table = s.load_table(load_paths({}, tmp_path))
    return s.resolve_session(table, "research", None)


def test_a_path_printed_on_stdout_is_moved_into_the_artifact_dir(session):
    started = time.time() - 1
    shot = session.scratch_dir / "tmp" / "shot.png"
    shot.parent.mkdir()
    shot.write_bytes(PNG)
    found, warnings = a.collect(session, f"saved {shot}\n", started, now=lambda: "2026-09-04T12:00:00Z")
    assert warnings == []
    assert len(found) == 1 and found[0]["kind"] == "screenshot" and found[0]["mime_type"] == "image/png"
    assert found[0]["path"].startswith(str(session.artifact_dir)) and found[0]["bytes"] == len(PNG)
    assert found[0]["captured_at"] == "2026-09-04T12:00:00Z"
    assert not shot.exists() and os.path.exists(found[0]["path"])


def test_new_files_in_the_artifact_dir_are_reported_without_a_stdout_mention(session):
    started = time.time() - 1
    (session.artifact_dir / "shot-1.jpg").write_bytes(JPEG)
    found, _ = a.collect(session, "", started, now=lambda: "t")
    assert [x["mime_type"] for x in found] == ["image/jpeg"]


def test_a_path_outside_the_session_dirs_is_skipped_with_a_warning(session, tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG)
    found, warnings = a.collect(session, f"{outside}\n", time.time() - 1, now=lambda: "t")
    assert found == [] and warnings == [f"artifact_skipped: {outside} is outside the session directories"]
    assert outside.exists()


def test_a_file_older_than_the_exec_is_ignored(session):
    old = session.scratch_dir / "old.png"
    old.write_bytes(PNG)
    os.utime(old, (1_600_000_000, 1_600_000_000))
    found, warnings = a.collect(session, f"{old}\n", time.time() - 1, now=lambda: "t")
    assert found == [] and warnings == []


def test_wrong_magic_and_oversize_are_skipped(session, monkeypatch):
    monkeypatch.setattr(a, "ARTIFACT_MAX_BYTES", 16)
    fake = session.scratch_dir / "fake.png"
    fake.write_bytes(b"not an image")
    big = session.scratch_dir / "big.png"
    big.write_bytes(PNG)
    _, warnings = a.collect(session, f"{fake}\n{big}\n", time.time() - 1, now=lambda: "t")
    assert warnings == [
        f"artifact_skipped: {fake} is not a supported image",
        f"artifact_skipped: {big} exceeds 16 bytes",
    ]


def test_prune_removes_only_files_past_retention(tmp_path):
    paths = load_paths({}, tmp_path)
    table = s.load_table(paths)
    session = s.resolve_session(table, "research", None)
    old = session.artifact_dir / "old.png"
    old.write_bytes(PNG)
    stamp = time.time() - (a.ARTIFACT_RETENTION_DAYS + 1) * 86400
    os.utime(old, (stamp, stamp))
    fresh = session.artifact_dir / "fresh.png"
    fresh.write_bytes(PNG)
    assert a.prune(paths) == 1
    assert not old.exists() and fresh.exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_artifacts.py -q`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `artifacts.py`**

```python
"""Screenshot collection: what the child wrote, checked, contained, and moved under the session's artifact dir.

Two sources, as Hermes does it: image paths printed on stdout, plus anything new in the artifact
dir itself (the Camoufox worker writes there directly). A candidate is reported only when it sits
under the session's own directories, carries a known image signature, and fits the size cap.
"""

from __future__ import annotations

import datetime as dt
import pathlib as pl
import re
import time
import typing as tp

from .protocol import ARTIFACT_MAX_BYTES, ARTIFACT_RETENTION_DAYS, Artifact
from .runtime_paths import Paths
from .sessions import Session

IMAGE_PATH_RE = re.compile(r"(/[^\s'\"`<>|]+?\.(?:png|jpe?g|webp))\b", re.IGNORECASE)
SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
)
EXTENSION_FOR_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _mime(path: pl.Path) -> str | None:
    with path.open("rb") as handle:
        head = handle.read(16)
    for signature, mime in SIGNATURES:
        if head.startswith(signature):
            return mime
    return None


def _contained(path: pl.Path, session: Session) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in (session.scratch_dir, session.artifact_dir))


def _candidates(session: Session, stdout: str, started_at: float) -> list[pl.Path]:
    printed = [pl.Path(match) for match in IMAGE_PATH_RE.findall(stdout)]
    present = [path for path in session.artifact_dir.iterdir() if path.is_file() and not path.name.startswith(".")]
    seen: dict[pl.Path, None] = {}
    for path in [*printed, *present]:
        if path.is_file() and path.stat().st_mtime >= started_at:
            seen.setdefault(path.resolve(), None)
    return list(seen)


def collect(session: Session, stdout: str, started_at: float, now: tp.Callable[[], str]) -> tuple[list[Artifact], list[str]]:
    found: list[Artifact] = []
    warnings: list[str] = []
    for index, path in enumerate(_candidates(session, stdout, started_at), start=1):
        if not _contained(path, session):
            warnings.append(f"artifact_skipped: {path} is outside the session directories")
            continue
        mime = _mime(path)
        if mime is None:
            warnings.append(f"artifact_skipped: {path} is not a supported image")
            continue
        size = path.stat().st_size
        if size > ARTIFACT_MAX_BYTES:
            warnings.append(f"artifact_skipped: {path} exceeds {ARTIFACT_MAX_BYTES} bytes")
            continue
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        target = session.artifact_dir / f"{stamp}-{index}.{EXTENSION_FOR_MIME[mime]}"
        if path != target:
            path.replace(target)
        found.append({"kind": "screenshot", "path": str(target), "mime_type": mime, "bytes": size, "captured_at": now()})
    return found, warnings


def prune(paths: Paths, now: float | None = None) -> int:
    cutoff = (time.time() if now is None else now) - ARTIFACT_RETENTION_DAYS * 86400
    removed = 0
    if not paths.artifacts.is_dir():
        return 0
    for path in paths.artifacts.rglob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed
```

Note on the "present" source: a file already in the artifact dir that the collector itself named on a prior exec has an mtime before `started_at`, so it is not re-reported.

- [ ] **Step 4: Run the tests**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_artifacts.py -q`
Expected: PASS. If the oversize test's ordering differs, sort `_candidates` output by path before returning.

- [ ] **Step 5: Commit**

```bash
git add agent/skills/browser/cli
git commit -m "feat(skills/browser): artifact collection with containment and retention"
```

---

### Task 6: Chromium runtime and the browser-use exec child

**Files:**
- Create: `agent/skills/browser/cli/src/vesta_browser/chromium.py`
- Test: `agent/skills/browser/cli/tests/test_chromium.py`, `agent/skills/browser/cli/tests/fakes.py`

**Interfaces:**
- Produces: `@dataclass class ChromiumRuntime(process: asyncio.subprocess.Process, port: int)`; `@dataclass class ExecOutcome(stdout: str, stderr: str, exit_code: int | None, duration_ms: int, timed_out: bool, cancelled: bool, capability_mismatch: str | None, warnings: list[str])`; `async def start(session: Session, paths: Paths) -> ChromiumRuntime`; `async def exec_code(runtime, session, paths, code: str, timeout_s: int) -> ExecOutcome`; `async def observe(runtime) -> PageInfo`; `async def stop(runtime, session) -> None`; `def child_env(session, port) -> dict[str, str]`; `def launch_argv(paths, session) -> list[str]`; `CHROMIUM_READY_TIMEOUT_SECS = 30`, `OBSERVE_TIMEOUT_SECS = 5`, `HARNESS_STOP_GRACE_SECS = 3`.
- The same `ExecOutcome` type is reused by Task 8; define it here and import it there.

The fake Chromium is a Python script that writes `DevToolsActivePort` and serves `/json/version` and `/json/list` on that port until killed. The fake browser-use is a script that echoes env and stdin as the daemon would see them.

- [ ] **Step 1: Write the fakes**

```python
# agent/skills/browser/cli/tests/fakes.py
"""Stand-ins for chromium and browser-use, written as executable scripts into a tmp bin dir."""

import pathlib as pl
import stat
import sys

FAKE_CHROMIUM = f"""#!{sys.executable}
import http.server, json, pathlib, sys, threading
args = sys.argv[1:]
profile = next(a.split("=", 1)[1] for a in args if a.startswith("--user-data-dir="))
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = {{"webSocketDebuggerUrl": "ws://127.0.0.1:%d/devtools/browser/x" % self.server.server_port}}
        if self.path == "/json/list":
            body = [{{"type": "page", "id": "T1", "url": "https://example.com/", "title": "Example Domain"}}]
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
pathlib.Path(profile, "DevToolsActivePort").write_text(f"{{srv.server_port}}\\n/devtools/browser/x\\n")
srv.serve_forever()
"""

FAKE_BROWSER_USE = f"""#!{sys.executable}
import json, os, sys, time
code = sys.stdin.read()
if "SLEEP" in code:
    time.sleep(30)
if "FAIL" in code:
    print("boom", file=sys.stderr); sys.exit(1)
if "SHOT" in code:
    p = os.path.join(os.environ["BH_TMP_DIR"], "shot.png"); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b"\\x89PNG\\r\\n\\x1a\\n" + b"0" * 8); print(p)
print(json.dumps({{k: os.environ[k] for k in sorted(os.environ)}}))
"""


def write_fakes(bin_dir: pl.Path) -> dict[str, str]:
    bin_dir.mkdir(exist_ok=True)
    env = {}
    for name, body, key in (("chromium", FAKE_CHROMIUM, "VESTA_BROWSER_CHROMIUM"), ("browser-use", FAKE_BROWSER_USE, "VESTA_BROWSER_BROWSER_USE")):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        env[key] = str(path)
    return env
```

- [ ] **Step 2: Write the failing tests**

```python
# agent/skills/browser/cli/tests/test_chromium.py
import asyncio
import json
import os

import pytest

from vesta_browser import chromium, sessions
from vesta_browser.runtime_paths import load_paths

from .fakes import write_fakes


@pytest.fixture
def rig(tmp_path):
    env = write_fakes(tmp_path / "bin")
    paths = load_paths(env, tmp_path)
    table = sessions.load_table(paths)
    session = sessions.resolve_session(table, "research", None)
    return paths, session


def _run(coro):
    return asyncio.run(coro)


def test_launch_argv_is_headless_sandboxless_and_profile_scoped(rig):
    paths, session = rig
    argv = chromium.launch_argv(paths, session)
    assert argv[0] == str(paths.chromium_exe)
    assert "--headless=new" in argv and "--no-sandbox" in argv and "--remote-debugging-port=0" in argv
    assert f"--user-data-dir={session.profile_dir}" in argv


def test_child_env_is_minimal_and_points_the_harness_at_the_session(rig, monkeypatch):
    paths, session = rig
    monkeypatch.setenv("AGENT_TOKEN", "secret")
    monkeypatch.setenv("PYTHONPATH", "/x")
    monkeypatch.setenv("DISPLAY", ":99")
    env = chromium.child_env(session, 4321)
    assert set(env) == {"PATH", "HOME", "LANG", "TMPDIR", "BH_RUNTIME_DIR", "BH_TMP_DIR", "BH_HOME", "BU_NAME", "BU_CDP_URL",
                        "BH_UPDATE_CHECK", "BH_TELEMETRY", "PYTHONUNBUFFERED"}
    assert env["BU_NAME"] == "research" and env["BU_CDP_URL"] == "http://127.0.0.1:4321"
    assert env["BH_RUNTIME_DIR"] == str(session.scratch_dir / "runtime") and env["BH_TMP_DIR"] == str(session.scratch_dir / "tmp")
    assert env["BH_UPDATE_CHECK"] == "0" and env["BH_TELEMETRY"] == "0"


def test_start_discovers_the_devtools_port_and_exec_runs_the_child(rig):
    paths, session = rig

    async def run():
        runtime = await chromium.start(session, paths)
        try:
            outcome = await chromium.exec_code(runtime, session, paths, "print('hi')", timeout_s=10)
            page = await chromium.observe(runtime)
        finally:
            await chromium.stop(runtime, session)
        return runtime, outcome, page

    runtime, outcome, page = _run(run())
    assert runtime.port > 0 and outcome.exit_code == 0 and not outcome.timed_out
    env_seen = json.loads(outcome.stdout.strip().splitlines()[-1])
    assert env_seen["BU_CDP_URL"] == f"http://127.0.0.1:{runtime.port}"
    assert page == {"state": "ready", "tab_id": "T1", "url": "https://example.com/", "title": "Example Domain", "observed_at": page["observed_at"]}
    assert runtime.process.returncode is not None


def test_timeout_kills_the_child_and_keeps_the_browser(rig):
    paths, session = rig

    async def run():
        runtime = await chromium.start(session, paths)
        try:
            outcome = await chromium.exec_code(runtime, session, paths, "SLEEP", timeout_s=1)
            alive = runtime.process.returncode is None
        finally:
            await chromium.stop(runtime, session)
        return outcome, alive

    outcome, alive = _run(run())
    assert outcome.timed_out is True and alive is True


def test_a_failing_child_reports_its_exit_code_and_stderr(rig):
    paths, session = rig

    async def run():
        runtime = await chromium.start(session, paths)
        try:
            return await chromium.exec_code(runtime, session, paths, "FAIL", timeout_s=10)
        finally:
            await chromium.stop(runtime, session)

    outcome = _run(run())
    assert outcome.exit_code == 1 and "boom" in outcome.stderr


def test_start_fails_engine_unavailable_when_the_binary_is_missing(tmp_path):
    paths = load_paths({"VESTA_BROWSER_CHROMIUM": str(tmp_path / "nope")}, tmp_path)
    session = sessions.resolve_session(sessions.load_table(paths), "research", None)
    with pytest.raises(chromium.p.BrowserError) as excinfo:
        _run(chromium.start(session, paths))
    assert excinfo.value.err["code"] == "engine_unavailable" and excinfo.value.err["phase"] == "launch"
```

- [ ] **Step 3: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_chromium.py -q`
Expected: FAIL, module not found.

- [ ] **Step 4: Write `chromium.py`**

```python
"""The standard route: one headless Chromium per session, one browser-use child per exec.

Chromium picks a free DevTools port and writes it to `<profile>/DevToolsActivePort`; the child gets
that port as `BU_CDP_URL`, so Browser Harness never launches a browser of its own. Browser Harness
spawns its own per-`BU_NAME` daemon under `BH_RUNTIME_DIR`, which lives in the session scratch dir
so the daemon here can find and stop it.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import os
import pathlib as pl
import signal
import time
import urllib.request

from . import protocol as p
from .runtime_paths import Paths
from .serve import now_iso
from .sessions import Session

CHROMIUM_READY_TIMEOUT_SECS = 30
READY_POLL_SECS = 0.1
OBSERVE_TIMEOUT_SECS = 5
HARNESS_STOP_GRACE_SECS = 3
BROWSER_STOP_GRACE_SECS = 5


@dataclasses.dataclass
class ChromiumRuntime:
    process: asyncio.subprocess.Process
    port: int


@dataclasses.dataclass
class ExecOutcome:
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int
    timed_out: bool = False
    cancelled: bool = False
    capability_mismatch: str | None = None
    warnings: list[str] = dataclasses.field(default_factory=list)


def launch_argv(paths: Paths, session: Session) -> list[str]:
    return [
        str(paths.chromium_exe),
        "--headless=new",
        "--no-sandbox",
        "--remote-debugging-port=0",
        f"--user-data-dir={session.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "about:blank",
    ]


def child_env(session: Session, port: int) -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"] if "PATH" in os.environ else "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(pl.Path.home()),
        "LANG": os.environ["LANG"] if "LANG" in os.environ else "C.UTF-8",
        "TMPDIR": str(session.scratch_dir / "tmp"),
        "BH_RUNTIME_DIR": str(session.scratch_dir / "runtime"),
        "BH_TMP_DIR": str(session.scratch_dir / "tmp"),
        "BH_HOME": str(session.scratch_dir / "home"),
        "BU_NAME": session.name,
        "BU_CDP_URL": f"http://127.0.0.1:{port}",
        "BH_UPDATE_CHECK": "0",
        "BH_TELEMETRY": "0",
        "PYTHONUNBUFFERED": "1",
    }


def _unavailable(message: str) -> p.BrowserError:
    return p.BrowserError(p.error("engine_unavailable", "launch", message, retryable=True, suggested_action="run: browser doctor"))


def _fetch_json(url: str) -> p.JsonValue:
    with urllib.request.urlopen(url, timeout=OBSERVE_TIMEOUT_SECS) as response:
        return json.loads(response.read())


async def start(session: Session, paths: Paths) -> ChromiumRuntime:
    if not paths.chromium_exe.is_file():
        raise _unavailable(f"chromium binary missing at {paths.chromium_exe}")
    if not paths.browser_use_bin.is_file():
        raise _unavailable(f"browser-use executor missing at {paths.browser_use_bin}; run the SETUP.md uv sync step")
    for sub in ("tmp", "runtime", "home"):
        (session.scratch_dir / sub).mkdir(exist_ok=True)
    port_file = session.profile_dir / "DevToolsActivePort"
    port_file.unlink(missing_ok=True)
    env = {"PATH": child_env(session, 0)["PATH"], "HOME": str(pl.Path.home())}
    process = await asyncio.create_subprocess_exec(
        *launch_argv(paths, session), env=env, start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    deadline = time.monotonic() + CHROMIUM_READY_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if process.returncode is not None:
            raise _unavailable(f"chromium exited with {process.returncode} during startup")
        if port_file.is_file():
            first = port_file.read_text().splitlines()
            if first and first[0].isdigit():
                port = int(first[0])
                try:
                    await asyncio.to_thread(_fetch_json, f"http://127.0.0.1:{port}/json/version")
                except OSError:
                    pass
                else:
                    return ChromiumRuntime(process=process, port=port)
        await asyncio.sleep(READY_POLL_SECS)
    await _kill_group(process, BROWSER_STOP_GRACE_SECS)
    raise _unavailable(f"chromium did not expose DevTools within {CHROMIUM_READY_TIMEOUT_SECS}s")


async def _kill_group(process: asyncio.subprocess.Process, grace: float) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), grace)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


async def exec_code(runtime: ChromiumRuntime, session: Session, paths: Paths, code: str, timeout_s: int) -> ExecOutcome:
    started = time.monotonic()
    child = await asyncio.create_subprocess_exec(
        str(paths.browser_use_bin), env=child_env(session, runtime.port), cwd=str(session.artifact_dir),
        start_new_session=True, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(child.communicate(code.encode()), timeout_s)
    except TimeoutError:
        await _kill_group(child, 1)
        return ExecOutcome("", "", None, int((time.monotonic() - started) * 1000), timed_out=True)
    except asyncio.CancelledError:
        await _kill_group(child, 1)
        raise
    return ExecOutcome(out.decode(errors="replace"), err.decode(errors="replace"), child.returncode, int((time.monotonic() - started) * 1000))


async def observe(runtime: ChromiumRuntime) -> p.PageInfo:
    try:
        targets = await asyncio.to_thread(_fetch_json, f"http://127.0.0.1:{runtime.port}/json/list")
    except (OSError, ValueError):
        return p.page_unavailable()
    if not isinstance(targets, list):
        return p.page_unavailable()
    for target in targets:
        if isinstance(target, dict) and target["type"] == "page" and not str(target["url"]).startswith(("chrome://", "devtools://")):
            return {"state": "ready", "tab_id": str(target["id"]), "url": str(target["url"]), "title": str(target["title"]), "observed_at": now_iso()}
    return p.page_unavailable()


def _harness_pid(session: Session) -> int | None:
    record = session.scratch_dir / "runtime" / "bu.pid"
    if not record.is_file():
        return None
    text = record.read_text().strip()
    try:
        parsed = json.loads(text)
        return int(parsed["pid"]) if isinstance(parsed, dict) else int(text)
    except (ValueError, KeyError):
        return None


async def stop(runtime: ChromiumRuntime, session: Session) -> None:
    pid = _harness_pid(session)
    if pid is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
        await asyncio.sleep(0)
    await _kill_group(runtime.process, BROWSER_STOP_GRACE_SECS)
    if pid is not None:
        await asyncio.sleep(HARNESS_STOP_GRACE_SECS if _pid_alive(pid) else 0)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
```

`now_iso` lives in `serve.py` today; to keep the graph a DAG (serve imports chromium in Task 9), move `now_iso` into `protocol.py` in this task and import it from there in both modules.

- [ ] **Step 5: Run the tests**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_chromium.py -q`
Expected: PASS. The fake chromium ignores `about:blank`; fine.

- [ ] **Step 6: Commit**

```bash
git add agent/skills/browser/cli
git commit -m "feat(skills/browser): chromium runtime with browser-use exec children"
```

---

### Task 7: The Camoufox worker (stealth executor)

**Files:**
- Create: `agent/skills/browser/engines/camoufox/worker.py`
- Create: `agent/skills/browser/cli/tests/fake_camoufox/camoufox/__init__.py`, `agent/skills/browser/cli/tests/fake_camoufox/camoufox/sync_api.py`
- Test: `agent/skills/browser/cli/tests/test_worker.py`

**Interfaces:**
- The worker is a standalone script run as `<camoufox venv python> worker.py --profile <dir> --executable <path> --config <json file> --artifacts <dir> [--headed]`. It imports only stdlib plus `camoufox.sync_api`. It prints `{"ready": true}` once, then answers one JSON line per request line on stdin:
  - `{"op": "exec", "code": "<python>"}` → `{"stdout": str, "stderr": str, "exit_code": 0|1, "capability_mismatch": str|null, "page": {"tab_id", "url", "title"} | null}`
  - `{"op": "observe"}` → `{"page": {...} | null}`
  - `{"op": "stop"}` → `{"stopped": true}` then exits 0.
- `build_globals(state: WorkerState) -> dict[str, object]` exposes exactly `PORTABLE_HELPERS` plus `page`, `context`, `cdp`. Task 8 supervises it; Task 9's tests import `protocol.PORTABLE_HELPERS` and compare with the worker's `PORTABLE_HELPERS` tuple (duplicated in the worker because it cannot import the cli package; the test pins them equal).

- [ ] **Step 1: Write the fake camoufox**

```python
# agent/skills/browser/cli/tests/fake_camoufox/camoufox/__init__.py
```

```python
# agent/skills/browser/cli/tests/fake_camoufox/camoufox/sync_api.py
"""A recording stand-in for camoufox.sync_api.Camoufox: enough Playwright surface for the worker's helpers."""

import json
import pathlib as pl


class _Mouse:
    def __init__(self, log):
        self.log = log

    def click(self, x, y, button="left", click_count=1):
        self.log.append(("click", x, y, button, click_count))

    def move(self, x, y):
        self.log.append(("move", x, y))

    def wheel(self, dx, dy):
        self.log.append(("wheel", dx, dy))


class _Keyboard:
    def __init__(self, log):
        self.log = log

    def type(self, text):
        self.log.append(("type", text))

    def press(self, key):
        self.log.append(("press", key))


class FakePage:
    def __init__(self, context, url="about:blank"):
        self.context = context
        self.url = url
        self._title = "blank"
        self.log = context.log
        self.mouse = _Mouse(self.log)
        self.keyboard = _Keyboard(self.log)
        self.closed = False

    def goto(self, url, **_):
        self.url = url
        self._title = "Title of " + url
        self.log.append(("goto", url))
        return None

    def title(self):
        return self._title

    def evaluate(self, expression, arg=None):
        self.log.append(("evaluate", expression))
        if expression.startswith("() => ({"):
            return {"url": self.url, "title": self._title, "w": 1280, "h": 800, "sx": 0, "sy": 0, "pw": 1280, "ph": 2000}
        if expression == "1 + 1":
            return 2
        if expression == "throw":
            raise RuntimeError("Evaluation failed: boom")
        return None

    def fill(self, selector, text, **_):
        self.log.append(("fill", selector, text))

    def wait_for_load_state(self, state="load", timeout=None):
        self.log.append(("wait_for_load_state", state))

    def wait_for_selector(self, selector, state="attached", timeout=None):
        self.log.append(("wait_for_selector", selector, state))
        if selector == "#never":
            raise TimeoutError("timeout")

    def screenshot(self, path=None, full_page=False):
        pl.Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 8)
        self.log.append(("screenshot", path, full_page))

    def set_input_files(self, selector, path):
        self.log.append(("upload", selector, path))

    def bring_to_front(self):
        self.log.append(("front", self.url))

    def close(self):
        self.closed = True
        self.context.pages.remove(self)


class FakeContext:
    def __init__(self):
        self.log = []
        self.pages = [FakePage(self)]

    def new_page(self):
        page = FakePage(self)
        self.pages.append(page)
        return page


class Camoufox:
    """Records launch options to `<user_data_dir>/launch.json` so a test can assert them."""

    def __init__(self, **options):
        self.options = options

    def __enter__(self):
        pl.Path(self.options["user_data_dir"], "launch.json").write_text(json.dumps({k: str(v) for k, v in self.options.items()}))
        return FakeContext()

    def __exit__(self, *exc):
        return False
```

- [ ] **Step 2: Write the failing worker tests**

```python
# agent/skills/browser/cli/tests/test_worker.py
"""Drives the real worker script under the fake camoufox package, over its stdin/stdout protocol."""

import json
import os
import pathlib as pl
import subprocess
import sys

import pytest

from vesta_browser import protocol as p
from vesta_browser.runtime_paths import load_paths

FAKE = pl.Path(__file__).parent / "fake_camoufox"


@pytest.fixture
def worker(tmp_path):
    paths = load_paths({}, tmp_path)
    profile = tmp_path / "profile"
    profile.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"navigator.userAgent": "UA"}))
    proc = subprocess.Popen(
        [sys.executable, str(paths.worker_script), "--profile", str(profile), "--executable", "/opt/camoufox/x/camoufox",
         "--config", str(config), "--artifacts", str(artifacts)],
        env={**os.environ, "PYTHONPATH": str(FAKE)}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert json.loads(proc.stdout.readline()) == {"ready": True}

    def ask(payload):
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    yield ask, profile, artifacts
    proc.kill()
    proc.wait()


def test_launch_options_are_persistent_headless_and_pinned(worker):
    _, profile, _ = worker
    launch = json.loads((profile / "launch.json").read_text())
    assert launch["persistent_context"] == "True" and launch["user_data_dir"] == str(profile)
    assert launch["executable_path"] == "/opt/camoufox/x/camoufox" and launch["headless"] == "True"
    assert launch["i_know_what_im_doing"] == "True" and "navigator.userAgent" in launch["config"]


def test_exec_captures_stdout_and_observes_the_page(worker):
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "new_tab('https://example.com'); print(page_info()['title'])"})
    assert res["exit_code"] == 0 and res["stdout"] == "Title of https://example.com\n" and res["stderr"] == ""
    assert res["page"]["url"] == "https://example.com" and res["page"]["tab_id"].startswith("tab")


def test_variables_do_not_survive_between_execs(worker):
    ask, _, _ = worker
    assert ask({"op": "exec", "code": "x = 1"})["exit_code"] == 0
    res = ask({"op": "exec", "code": "print(x)"})
    assert res["exit_code"] == 1 and "NameError" in res["stderr"]


def test_cdp_raises_a_capability_mismatch(worker):
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "cdp('Page.navigate', url='x')"})
    assert res["exit_code"] == 1 and res["capability_mismatch"] == "cdp"


def test_page_global_follows_new_tab_and_switch_tab(worker):
    ask, _, _ = worker
    code = "a = current_tab()['target_id']; new_tab('https://b'); print(page.url); switch_tab(a); print(page.url)"
    res = ask({"op": "exec", "code": code})
    assert res["stdout"] == "https://b\nabout:blank\n"


def test_screenshot_lands_in_the_artifact_dir(worker):
    ask, _, artifacts = worker
    res = ask({"op": "exec", "code": "print(capture_screenshot())"})
    printed = pl.Path(res["stdout"].strip())
    assert printed.parent == artifacts and printed.is_file()


def test_wait_for_element_returns_false_on_timeout_like_the_harness(worker):
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "print(wait_for_element('#never', timeout=0.1)); print(wait_for_element('#ok'))"})
    assert res["stdout"] == "False\nTrue\n"


def test_js_returns_values_and_surfaces_errors(worker):
    ask, _, _ = worker
    assert ask({"op": "exec", "code": "print(js('1 + 1'))"})["stdout"] == "2\n"
    res = ask({"op": "exec", "code": "js('throw')"})
    assert res["exit_code"] == 1 and "boom" in res["stderr"]


def test_press_key_maps_modifier_bits(worker):
    ask, _, _ = worker
    ask({"op": "exec", "code": "press_key('a', modifiers=2 | 8)"})
    res = ask({"op": "exec", "code": "print(context.log[-1])"})
    assert res["stdout"] == "('press', 'Control+Shift+a')\n"


def test_portable_helper_list_matches_the_protocol(worker):
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "print(sorted(k for k in globals() if not k.startswith('_') and k not in ('page', 'context', 'cdp')))"})
    assert json.loads(res["stdout"].replace("'", '"')) == sorted(p.PORTABLE_HELPERS)


def test_stop_ends_the_worker(worker):
    ask, _, _ = worker
    assert ask({"op": "stop"}) == {"stopped": True}
```

- [ ] **Step 3: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_worker.py -q`
Expected: FAIL (worker script missing, fixture assertion on the ready line).

- [ ] **Step 4: Write `worker.py`**

```python
"""The stealth executor: one Camoufox (Playwright Firefox) per session, one process per session.

Runs in the camoufox engine venv. The daemon starts it, speaks JSON lines over stdin/stdout, and
kills the whole process group on a timeout; the profile on disk is what survives. Each exec gets
fresh globals carrying the portable helpers, `page`, `context`, and a `cdp` that refuses.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import pathlib as pl
import sys
import time
import traceback
import typing as tp

PORTABLE_HELPERS: tuple[str, ...] = (
    "new_tab", "goto_url", "page_info",
    "current_tab", "list_tabs", "switch_tab", "close_tab", "ensure_real_tab",
    "click_at_xy", "type_text", "fill_input", "press_key", "scroll",
    "js", "wait", "wait_for_load", "wait_for_element", "wait_for_network_idle",
    "capture_screenshot", "upload_file",
)
MODIFIER_NAMES = ((1, "Alt"), (2, "Control"), (4, "Meta"), (8, "Shift"))
PAGE_INFO_JS = "() => ({url: location.href, title: document.title, w: innerWidth, h: innerHeight, sx: scrollX, sy: scrollY, pw: document.documentElement.scrollWidth, ph: document.documentElement.scrollHeight})"


class CapabilityMismatch(Exception):
    def __init__(self, operation: str) -> None:
        super().__init__(f"{operation}() is unavailable on camoufox; use the portable helpers or the Playwright page object")
        self.operation = operation


class WorkerState:
    """Mutable per-process state the helper closures share; the one holder, no methods."""

    def __init__(self, context: tp.Any, artifacts: pl.Path) -> None:
        self.context = context
        self.artifacts = artifacts
        self.tabs: dict[str, tp.Any] = {}
        self.page: tp.Any = None
        self.exec_globals: dict[str, object] = {}
        self.shots = 0


def _tab_id(state: WorkerState, page: tp.Any) -> str:
    for tab_id, known in state.tabs.items():
        if known is page:
            return tab_id
    tab_id = f"tab{len(state.tabs) + 1}"
    state.tabs[tab_id] = page
    return tab_id


def _set_page(state: WorkerState, page: tp.Any) -> None:
    state.page = page
    state.exec_globals["page"] = page


def _tab(state: WorkerState, page: tp.Any) -> dict[str, str]:
    tab_id = _tab_id(state, page)
    return {"targetId": tab_id, "target_id": tab_id, "url": page.url, "title": page.title()}


def _resolve(state: WorkerState, target: object) -> tp.Any:
    tab_id = target["target_id"] if isinstance(target, dict) else str(target)
    return state.tabs[tab_id]


def build_globals(state: WorkerState) -> dict[str, object]:
    def new_tab(url: str = "about:blank") -> str:
        page = state.context.new_page()
        _set_page(state, page)
        page.goto(url)
        return _tab_id(state, page)

    def goto_url(url: str) -> dict[str, str]:
        state.page.goto(url)
        return {"url": state.page.url}

    def page_info() -> dict[str, object]:
        return state.page.evaluate(PAGE_INFO_JS)

    def current_tab() -> dict[str, str]:
        return _tab(state, state.page)

    def list_tabs(include_chrome: bool = True) -> list[dict[str, str]]:
        return [_tab(state, page) for page in state.context.pages if include_chrome or not page.url.startswith("about:")]

    def switch_tab(target: object, activate: bool = False) -> str:
        page = _resolve(state, target)
        _set_page(state, page)
        if activate:
            page.bring_to_front()
        return _tab_id(state, page)

    def close_tab(target: object | None = None) -> None:
        page = state.page if target is None else _resolve(state, target)
        page.close()
        if page is state.page:
            _set_page(state, state.context.pages[-1] if state.context.pages else state.context.new_page())

    def ensure_real_tab() -> dict[str, str]:
        if state.page.url.startswith("about:") and len(state.context.pages) > 1:
            _set_page(state, state.context.pages[-1])
        return current_tab()

    def click_at_xy(x: float, y: float, button: str = "left", clicks: int = 1) -> None:
        state.page.mouse.click(x, y, button=button, click_count=clicks)

    def type_text(text: str) -> None:
        state.page.keyboard.type(text)

    def fill_input(selector: str, text: str, clear_first: bool = True, timeout: float = 0.0) -> None:
        state.page.fill(selector, text, timeout=timeout * 1000 if timeout else None)

    def press_key(key: str, modifiers: int = 0) -> None:
        prefix = "".join(f"{name}+" for bit, name in MODIFIER_NAMES if modifiers & bit)
        state.page.keyboard.press(prefix + key)

    def scroll(x: float, y: float, dy: float = -300, dx: float = 0) -> None:
        state.page.mouse.move(x, y)
        state.page.mouse.wheel(dx, dy)

    def js(expression: str, target_id: str | None = None) -> object:
        page = state.page if target_id is None else state.tabs[target_id]
        return page.evaluate(expression)

    def wait(seconds: float = 1.0) -> None:
        time.sleep(seconds)

    def wait_for_load(timeout: float = 15.0) -> bool:
        try:
            state.page.wait_for_load_state("load", timeout=timeout * 1000)
        except Exception:  # Playwright raises its own TimeoutError subclass
            return False
        return True

    def wait_for_element(selector: str, timeout: float = 10.0, visible: bool = False) -> bool:
        try:
            state.page.wait_for_selector(selector, state="visible" if visible else "attached", timeout=timeout * 1000)
        except Exception:
            return False
        return True

    def wait_for_network_idle(timeout: float = 10.0, idle_ms: int = 500) -> bool:
        try:
            state.page.wait_for_load_state("networkidle", timeout=timeout * 1000)
        except Exception:
            return False
        return True

    def capture_screenshot(path: str | None = None, full: bool = False, max_dim: int | None = None) -> str:
        state.shots += 1
        target = pl.Path(path) if path else state.artifacts / f"shot-{state.shots}.png"
        state.page.screenshot(path=str(target), full_page=full)
        return str(target)

    def upload_file(selector: str, path: str) -> None:
        state.page.set_input_files(selector, path)

    def cdp(*_args: object, **_kwargs: object) -> tp.NoReturn:
        raise CapabilityMismatch("cdp")

    helpers = {name: value for name, value in locals().items() if name in PORTABLE_HELPERS}
    return {**helpers, "cdp": cdp, "context": state.context, "page": state.page, "__builtins__": __builtins__}


def observe(state: WorkerState) -> dict[str, str] | None:
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
            exec(code, state.exec_globals)  # noqa: S102 is not used here; exec is the executor's purpose
        except CapabilityMismatch as exc:
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
```

Remove the `# noqa` fragment on the `exec` line: escapes are banned repo-wide, and ruff's config for `agent/` must be checked. If `S102` fires, tune it once in `agent/ruff.toml` with a one-line justification (the worker's purpose is executing Vesta's program). `WorkerState` is a plain holder with `__init__` only, which is the dataclass idiom spelled out because the worker keeps `tp.Any` for Playwright objects it cannot type without importing Playwright at module import time; if ruff/ty complain about `tp.Any`, replace with `object` and the narrow `tp.Protocol` classes for `Page` and `Context` methods used here (goto, title, evaluate, fill, wait_for_load_state, wait_for_selector, screenshot, set_input_files, bring_to_front, close, url, mouse, keyboard, pages, new_page).

- [ ] **Step 5: Run the tests**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_worker.py -q`
Expected: PASS. The `page` global test relies on `_set_page` writing into `state.exec_globals`, which `build_globals` seeds and `run_exec` installs before `exec`.

- [ ] **Step 6: Commit**

```bash
git add agent/skills/browser/engines/camoufox/worker.py agent/skills/browser/cli/tests
git commit -m "feat(skills/browser): camoufox worker with the portable helper surface"
```

---

### Task 8: Camoufox supervisor

**Files:**
- Create: `agent/skills/browser/cli/src/vesta_browser/camoufox.py`
- Test: `agent/skills/browser/cli/tests/test_camoufox.py`

**Interfaces:**
- Produces: `@dataclass class CamoufoxRuntime(process: asyncio.subprocess.Process, config_path: Path, last_page: PageInfo)`; `async def start(session, paths, *, headed=False) -> CamoufoxRuntime`; `async def exec_code(runtime, session, paths, code, timeout_s) -> ExecOutcome` (same type as chromium); `async def observe(runtime) -> PageInfo`; `async def stop(runtime, session) -> None`; `CAMOUFOX_READY_TIMEOUT_SECS = 90`, `WORKER_STOP_GRACE_SECS = 5`.
- Consumes: `presets.select_preset(profile_dir)` and `camou` config as a JSON file in the scratch dir; `chromium.ExecOutcome`, `chromium._kill_group` (move `_kill_group` to a shared `procs.py` module: `async def kill_group(process, grace) -> None`, imported by both engines).
- After a timeout the runtime's process is dead: `exec_code` returns `timed_out=True`; Task 9 drops `session.runtime` so the next exec restarts the worker and adds the `worker_restarted` warning.

- [ ] **Step 1: Write the failing tests**

```python
# agent/skills/browser/cli/tests/test_camoufox.py
import asyncio
import json
import pathlib as pl
import sys

import pytest

from vesta_browser import camoufox, sessions
from vesta_browser.runtime_paths import load_paths

FAKE = pl.Path(__file__).parent / "fake_camoufox"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(FAKE))
    exe = tmp_path / "camoufox"
    exe.write_text("")
    env = {"VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable, "VESTA_BROWSER_CAMOUFOX_EXE": str(exe)}
    paths = load_paths(env, tmp_path)
    session = sessions.resolve_session(sessions.load_table(paths), "stealthy", "stealth")
    return paths, session


def test_start_writes_the_preset_config_and_the_worker_reports_ready(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths)
        try:
            return json.loads(runtime.config_path.read_text()), json.loads((session.profile_dir / "launch.json").read_text())
        finally:
            await camoufox.stop(runtime, session)

    config, launch = asyncio.run(run())
    assert config["showcursor"] is False and "navigator.userAgent" in config
    assert launch["user_data_dir"] == str(session.profile_dir) and launch["executable_path"] == str(paths.camoufox_exe)


def test_exec_returns_output_and_the_page(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths)
        try:
            outcome = await camoufox.exec_code(runtime, session, paths, "new_tab('https://a'); print('ok')", timeout_s=10)
            return outcome, await camoufox.observe(runtime)
        finally:
            await camoufox.stop(runtime, session)

    outcome, page = asyncio.run(run())
    assert outcome.exit_code == 0 and outcome.stdout == "ok\n" and outcome.capability_mismatch is None
    assert page["state"] == "ready" and page["url"] == "https://a"


def test_capability_mismatch_is_surfaced(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths)
        try:
            return await camoufox.exec_code(runtime, session, paths, "cdp('x')", timeout_s=10)
        finally:
            await camoufox.stop(runtime, session)

    outcome = asyncio.run(run())
    assert outcome.exit_code == 1 and outcome.capability_mismatch == "cdp"


def test_timeout_kills_the_worker(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths)
        outcome = await camoufox.exec_code(runtime, session, paths, "import time; time.sleep(30)", timeout_s=1)
        return outcome, runtime.process.returncode

    outcome, code = asyncio.run(run())
    assert outcome.timed_out is True and code is not None


def test_missing_binary_is_engine_unavailable(tmp_path):
    paths = load_paths({"VESTA_BROWSER_CAMOUFOX_EXE": str(tmp_path / "nope")}, tmp_path)
    session = sessions.resolve_session(sessions.load_table(paths), "s", "stealth")
    with pytest.raises(camoufox.p.BrowserError) as excinfo:
        asyncio.run(camoufox.start(session, paths))
    assert excinfo.value.err["code"] == "engine_unavailable"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_camoufox.py -q`
Expected: FAIL, module not found.

- [ ] **Step 3: Extract `procs.py` and write `camoufox.py`**

```python
# agent/skills/browser/cli/src/vesta_browser/procs.py
"""Process-group termination shared by both engines: TERM the group, wait, KILL what remains."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal


async def kill_group(process: asyncio.subprocess.Process, grace: float) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), grace)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
```

Replace `chromium._kill_group` with `from .procs import kill_group` and update its three call sites.

```python
# agent/skills/browser/cli/src/vesta_browser/camoufox.py
"""The stealth route: one supervised worker process per session, speaking JSON lines over pipes.

The worker (engines/camoufox/worker.py) owns the Camoufox browser in-process, so a timeout kills
the process group and the browser with it; the profile persists and the next exec restarts it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib as pl
import time

from . import protocol as p
from .chromium import ExecOutcome
from .presets import select_preset
from .procs import kill_group
from .runtime_paths import Paths
from .sessions import Session

CAMOUFOX_READY_TIMEOUT_SECS = 90
WORKER_STOP_GRACE_SECS = 5


@dataclasses.dataclass
class CamoufoxRuntime:
    process: asyncio.subprocess.Process
    config_path: pl.Path
    last_page: p.PageInfo


def _unavailable(message: str) -> p.BrowserError:
    return p.BrowserError(p.error("engine_unavailable", "launch", message, retryable=True, suggested_action="run: browser doctor"))


def _page_info(raw: p.JsonValue) -> p.PageInfo:
    if not isinstance(raw, dict):
        return p.page_unavailable()
    return {"state": "ready", "tab_id": str(raw["tab_id"]), "url": str(raw["url"]), "title": str(raw["title"]), "observed_at": p.now_iso()}


def worker_argv(paths: Paths, session: Session, config_path: pl.Path, headed: bool) -> list[str]:
    argv = [
        str(paths.camoufox_python), str(paths.worker_script),
        "--profile", str(session.profile_dir), "--executable", str(paths.camoufox_exe),
        "--config", str(config_path), "--artifacts", str(session.artifact_dir),
    ]
    return [*argv, "--headed"] if headed else argv


async def start(session: Session, paths: Paths, *, headed: bool = False) -> CamoufoxRuntime:
    for binary, label in ((paths.camoufox_python, "camoufox venv python"), (paths.camoufox_exe, "camoufox browser"), (paths.worker_script, "worker script")):
        if not binary.is_file():
            raise _unavailable(f"{label} missing at {binary}")
    config_path = session.scratch_dir / "camou-config.json"
    preset = {key: value for key, value in select_preset(session.profile_dir).items() if not key.startswith("_")}
    config_path.write_text(json.dumps(preset))
    process = await asyncio.create_subprocess_exec(
        *worker_argv(paths, session, config_path, headed), start_new_session=True,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    assert process.stdout is not None
    try:
        line = await asyncio.wait_for(process.stdout.readline(), CAMOUFOX_READY_TIMEOUT_SECS)
    except TimeoutError:
        await kill_group(process, 1)
        raise _unavailable(f"camoufox worker did not report ready within {CAMOUFOX_READY_TIMEOUT_SECS}s") from None
    if not line or json.loads(line) != {"ready": True}:
        await kill_group(process, 1)
        raise _unavailable(f"camoufox worker exited during startup (code {process.returncode})")
    return CamoufoxRuntime(process=process, config_path=config_path, last_page=p.page_unavailable())


async def _ask(runtime: CamoufoxRuntime, payload: dict[str, p.JsonValue], timeout_s: float) -> dict[str, p.JsonValue]:
    assert runtime.process.stdin is not None and runtime.process.stdout is not None
    runtime.process.stdin.write((json.dumps(payload) + "\n").encode())
    await runtime.process.stdin.drain()
    line = await asyncio.wait_for(runtime.process.stdout.readline(), timeout_s)
    if not line:
        raise ConnectionError("camoufox worker closed its pipe")
    answer = json.loads(line)
    if not isinstance(answer, dict):
        raise ConnectionError("camoufox worker answered with a non-object")
    return answer


async def exec_code(runtime: CamoufoxRuntime, session: Session, paths: Paths, code: str, timeout_s: int) -> ExecOutcome:
    started = time.monotonic()
    try:
        answer = await _ask(runtime, {"op": "exec", "code": code}, timeout_s)
    except TimeoutError:
        await kill_group(runtime.process, 1)
        return ExecOutcome("", "", None, int((time.monotonic() - started) * 1000), timed_out=True)
    except asyncio.CancelledError:
        await kill_group(runtime.process, 1)
        raise
    except (ConnectionError, ValueError) as exc:
        await kill_group(runtime.process, 1)
        return ExecOutcome("", str(exc), None, int((time.monotonic() - started) * 1000), warnings=["worker_restarted"])
    runtime.last_page = _page_info(answer["page"])
    mismatch = answer["capability_mismatch"]
    return ExecOutcome(
        str(answer["stdout"]), str(answer["stderr"]), int(str(answer["exit_code"])), int((time.monotonic() - started) * 1000),
        capability_mismatch=str(mismatch) if isinstance(mismatch, str) else None,
    )


async def observe(runtime: CamoufoxRuntime) -> p.PageInfo:
    if runtime.process.returncode is not None:
        return p.page_unavailable()
    try:
        answer = await _ask(runtime, {"op": "observe"}, 5)
    except (TimeoutError, ConnectionError, ValueError):
        return p.page_unavailable()
    runtime.last_page = _page_info(answer["page"])
    return runtime.last_page


async def stop(runtime: CamoufoxRuntime, session: Session) -> None:
    if runtime.process.returncode is None:
        try:
            await _ask(runtime, {"op": "stop"}, WORKER_STOP_GRACE_SECS)
        except (TimeoutError, ConnectionError, ValueError):
            pass
    await kill_group(runtime.process, WORKER_STOP_GRACE_SECS)
```

`p.now_iso` is the `now_iso` moved into `protocol.py` in Task 6. Replace the `assert` statements with explicit `if ... is None: raise RuntimeError(...)` if ruff's `S101` is on for `agent/` (check `agent/ruff.toml`).

- [ ] **Step 4: Run the engine tests**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_camoufox.py skills/browser/cli/tests/test_chromium.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/skills/browser/cli
git commit -m "feat(skills/browser): camoufox worker supervisor"
```

---

### Task 9: Exec, cancel, sessions, stop, idle sweep, and shutdown in the daemon

**Files:**
- Modify: `agent/skills/browser/cli/src/vesta_browser/serve.py`
- Test: `agent/skills/browser/cli/tests/test_serve_exec.py`

**Interfaces:**
- Produces ops: `exec {session, mode|null, timeout_s, code}`, `cancel {target_request_id}`, `sessions`, `session_stop {session}`, `stop_all`. `State` gains `table: SessionTable`.
- Engine dispatch: `ENGINES: dict[Engine, EngineModule]` where the two modules expose `start`, `exec_code`, `observe`, `stop` with the signatures from Tasks 6 and 8 (module objects are the namespace; no class).
- Consumes: everything from Tasks 2 to 8.

- [ ] **Step 1: Write the failing tests**

```python
# agent/skills/browser/cli/tests/test_serve_exec.py
import asyncio
import json
import pathlib as pl
import sys

import pytest

from vesta_browser import protocol as p
from vesta_browser import serve
from vesta_browser.runtime_paths import load_paths

from .fakes import write_fakes

FAKE = pl.Path(__file__).parent / "fake_camoufox"


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(FAKE))
    env = write_fakes(tmp_path / "bin")
    exe = tmp_path / "camoufox"
    exe.write_text("")
    env.update({"VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable, "VESTA_BROWSER_CAMOUFOX_EXE": str(exe)})
    return load_paths(env, tmp_path)


def _exec(session, code, mode=None, timeout_s=10, request_id="r1"):
    return {"version": 1, "op": "exec", "request_id": request_id, "session": session, "mode": mode, "timeout_s": timeout_s, "code": code}


def _with_daemon(paths, coro_fn):
    async def run():
        server = asyncio.create_task(serve.serve(paths))
        for _ in range(100):
            if paths.socket.exists():
                break
            await asyncio.sleep(0.02)
        try:
            return await coro_fn()
        finally:
            server.cancel()
            with pytest.raises(asyncio.CancelledError):
                await server

    return asyncio.run(run())


def test_exec_on_a_new_session_starts_chromium_and_returns_the_full_envelope(paths):
    async def run():
        return await serve.request(paths, _exec("research", "print('hi')"))

    res = _with_daemon(paths, run)
    assert res["ok"] is True and res["session"]["engine"] == "chromium" and res["session"]["state"] == "ready"
    assert res["page"]["url"] == "https://example.com/" and res["output"]["exit_code"] == 0
    assert res["artifacts"] == [] and res["warnings"] == []


def test_stealth_exec_runs_camoufox_and_pins_the_session(paths):
    async def run():
        first = await serve.request(paths, _exec("s", "print(1)", mode="stealth"))
        conflict = await serve.request(paths, _exec("s", "print(1)", mode="standard", request_id="r2"))
        inherit = await serve.request(paths, _exec("s", "print(2)", request_id="r3"))
        return first, conflict, inherit

    first, conflict, inherit = _with_daemon(paths, run)
    assert first["session"]["engine"] == "camoufox" and first["output"]["stdout"] == "1\n"
    assert conflict["ok"] is False and conflict["error"]["code"] == "session_engine_conflict"
    assert inherit["session"]["engine"] == "camoufox"


def test_a_screenshot_becomes_an_artifact(paths):
    async def run():
        return await serve.request(paths, _exec("research", "SHOT"))

    res = _with_daemon(paths, run)
    assert len(res["artifacts"]) == 1 and res["artifacts"][0]["mime_type"] == "image/png"
    assert res["artifacts"][0]["path"].startswith(str(paths.artifacts / "research"))


def test_failed_code_is_execution_failed_with_stderr_kept(paths):
    async def run():
        return await serve.request(paths, _exec("research", "FAIL"))

    res = _with_daemon(paths, run)
    assert res["ok"] is False and res["error"]["code"] == "execution_failed" and res["error"]["phase"] == "execution"
    assert "boom" in res["output"]["stderr"] and res["session"]["state"] == "ready" and res["page"]["state"] == "ready"


def test_cdp_on_camoufox_is_a_capability_mismatch(paths):
    async def run():
        return await serve.request(paths, _exec("s", "cdp('x')", mode="stealth"))

    res = _with_daemon(paths, run)
    assert res["error"]["code"] == "engine_capability_mismatch" and "camoufox" in res["error"]["message"]
    assert res["error"]["retryable"] is False and "new" in res["error"]["suggested_action"]


def test_timeout_is_clamped_and_reported(paths):
    async def run():
        clamped = await serve.request(paths, _exec("research", "print(1)", timeout_s=1))
        timed_out = await serve.request(paths, _exec("research", "SLEEP", timeout_s=5, request_id="r2"))
        return clamped, timed_out

    clamped, timed_out = _with_daemon(paths, run)
    assert "timeout_clamped" in clamped["warnings"]
    assert timed_out["error"]["code"] == "timed_out" and timed_out["error"]["retryable"] is True


def test_camoufox_timeout_restarts_the_worker_on_the_next_exec(paths):
    async def run():
        first = await serve.request(paths, _exec("s", "import time; time.sleep(30)", mode="stealth", timeout_s=5))
        second = await serve.request(paths, _exec("s", "print('back')", request_id="r2"))
        return first, second

    first, second = _with_daemon(paths, run)
    assert first["error"]["code"] == "timed_out" and first["session"]["state"] == "stopped"
    assert second["ok"] is True and "worker_restarted" in second["warnings"]


def test_cancel_ends_an_inflight_exec(paths):
    async def run():
        task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=30)))
        await asyncio.sleep(1.5)
        cancel = await serve.request(paths, {"version": 1, "op": "cancel", "request_id": "c1", "target_request_id": "r1"})
        return cancel, await task

    cancel, res = _with_daemon(paths, run)
    assert cancel["ok"] is True
    assert res["error"]["code"] == "cancelled" and res["session"]["state"] == "ready"


def test_busy_session_refuses_a_second_exec(paths):
    async def run():
        task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=30)))
        await asyncio.sleep(1.5)
        second = await serve.request(paths, _exec("research", "print(1)", request_id="r2"))
        await serve.request(paths, {"version": 1, "op": "cancel", "request_id": "c1", "target_request_id": "r1"})
        await task
        return second

    second = _with_daemon(paths, run)
    assert second["error"]["code"] == "invalid_request" and "busy" in second["error"]["message"]


def test_sessions_and_session_stop_and_stop_all(paths):
    async def run():
        await serve.request(paths, _exec("a", "print(1)"))
        await serve.request(paths, _exec("b", "print(1)", mode="stealth", request_id="r2"))
        listing = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l"})
        stopped = await serve.request(paths, {"version": 1, "op": "session_stop", "request_id": "s", "session": "a"})
        after = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l2"})
        stop_all = await serve.request(paths, {"version": 1, "op": "stop_all", "request_id": "sa"})
        final = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l3"})
        return listing, stopped, after, stop_all, final

    listing, stopped, after, stop_all, final = _with_daemon(paths, run)
    assert {s["name"]: (s["engine"], s["state"]) for s in listing["data"]["sessions"]} == {"a": ("chromium", "ready"), "b": ("camoufox", "ready")}
    assert stopped["ok"] is True
    assert {s["name"]: s["state"] for s in after["data"]["sessions"]} == {"a": "stopped", "b": "ready"}
    assert stop_all["data"]["stopped"] == ["b"]
    assert all(s["state"] == "stopped" for s in final["data"]["sessions"])


def test_bad_exec_requests_are_invalid(paths):
    async def run():
        empty = await serve.request(paths, _exec("research", ""))
        huge = await serve.request(paths, _exec("research", "x" * (p.CODE_MAX_BYTES + 1), request_id="r2"))
        mode = await serve.request(paths, _exec("research", "print(1)", mode="ninja", request_id="r3"))
        return empty, huge, mode

    for res in _with_daemon(paths, run):
        assert res["ok"] is False and res["error"]["code"] == "invalid_request"


def test_idle_sweep_stops_a_ready_session(paths, monkeypatch):
    monkeypatch.setattr(serve, "IDLE_SWEEP_SECS", 0.2)
    monkeypatch.setattr(serve.p, "SESSION_IDLE_STOP_SECS", 0)
    monkeypatch.setattr(serve.sessions_mod.p, "SESSION_IDLE_STOP_SECS", 0)

    async def run():
        await serve.request(paths, _exec("research", "print(1)"))
        await asyncio.sleep(1.0)
        return await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l"})

    res = _with_daemon(paths, run)
    assert res["data"]["sessions"][0]["state"] == "stopped"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_serve_exec.py -q`
Expected: FAIL (`exec` is an unknown op).

- [ ] **Step 3: Extend `serve.py`**

Add imports `from . import artifacts, camoufox, chromium, sessions as sessions_mod` and `import time`. Add `table: sessions_mod.SessionTable` to `State` (constructed in `serve()` via `sessions_mod.load_table(paths)`), plus these functions and handlers:

```python
ENGINES = {"chromium": chromium, "camoufox": camoufox}


def _validate_exec(request: dict[str, p.JsonValue]) -> tuple[str, p.Mode | None, int, str, list[str]]:
    """Returns (session, mode, timeout_s, code, warnings) or raises BrowserError(invalid_request)."""
    code = request["code"] if "code" in request else ""
    if not isinstance(code, str) or not code.strip():
        raise p.BrowserError(_invalid("code is empty"))
    if len(code.encode()) > p.CODE_MAX_BYTES:
        raise p.BrowserError(_invalid(f"code exceeds {p.CODE_MAX_BYTES} bytes"))
    session = request["session"] if "session" in request else p.DEFAULT_SESSION
    if not isinstance(session, str):
        raise p.BrowserError(_invalid("session must be a string"))
    mode = request["mode"] if "mode" in request else None
    if mode not in (None, "standard", "stealth"):
        raise p.BrowserError(_invalid("mode must be standard, stealth, or null"))
    raw_timeout = request["timeout_s"] if "timeout_s" in request else p.EXEC_TIMEOUT_DEFAULT_SECS
    if not isinstance(raw_timeout, int):
        raise p.BrowserError(_invalid("timeout_s must be an integer"))
    timeout = min(max(raw_timeout, p.EXEC_TIMEOUT_MIN_SECS), p.EXEC_TIMEOUT_MAX_SECS)
    warnings = ["timeout_clamped"] if timeout != raw_timeout else []
    return session, tp.cast(p.Mode | None, mode), timeout, code, warnings


async def _ensure_running(state: State, session: sessions_mod.Session) -> list[str]:
    """Starts the session's engine when it is not running. Returns warnings (worker_restarted after a kill)."""
    if session.runtime is not None:
        return []
    restarted = session.state == "stopped" and session.name in state.restart_pending
    state.restart_pending.discard(session.name)
    sessions_mod.mark(session, "starting")
    try:
        session.runtime = await ENGINES[session.engine].start(session, state.paths)
    except p.BrowserError:
        sessions_mod.mark(session, "stopped")
        raise
    sessions_mod.mark(session, "ready")
    return ["worker_restarted"] if restarted else []


async def _stop_session(state: State, session: sessions_mod.Session) -> None:
    runtime = session.runtime
    session.runtime = None
    if runtime is not None:
        await ENGINES[session.engine].stop(runtime, session)
    sessions_mod.mark(session, "stopped")


def _outcome_error(outcome: chromium.ExecOutcome, session: sessions_mod.Session) -> p.Error | None:
    if outcome.timed_out:
        return p.error("timed_out", "execution", f"execution exceeded its budget", retryable=True, suggested_action="raise --timeout (and the Bash timeout) or split the program")
    if outcome.cancelled:
        return p.error("cancelled", "execution", "the client cancelled this request", retryable=False, suggested_action="rerun when ready")
    if outcome.capability_mismatch is not None:
        other = "chromium" if session.engine == "camoufox" else "camoufox"
        return p.error(
            "engine_capability_mismatch", "execution",
            f"{outcome.capability_mismatch}() is unavailable on {session.engine}",
            retryable=False, suggested_action=f"change the code to the portable helpers, or start a new {other} session under a new name",
        )
    if outcome.exit_code != 0:
        return p.error("execution_failed", "execution", f"the program exited with {outcome.exit_code}", retryable=False, suggested_action="read output.stderr and fix the code")
    return None


async def op_exec(state: State, request: dict[str, p.JsonValue]) -> p.Result:
    request_id = str(request["request_id"])
    name, mode, timeout, code, warnings = _validate_exec(request)
    session = sessions_mod.resolve_session(state.table, name, mode)
    if session.state == "handed_over":
        raise p.BrowserError(p.error("handover_in_use", "routing", f"session {name!r} is handed over to the user", retryable=True, suggested_action="wait for browser handover stop"))
    if session.state == "busy":
        raise p.BrowserError(_invalid(f"session {name!r} is busy with request {session.request_id}"))
    warnings += await _ensure_running(state, session)
    assert session.runtime is not None
    engine = ENGINES[session.engine]
    sessions_mod.mark(session, "busy")
    session.request_id = request_id
    started_at = time.time()
    task = asyncio.ensure_future(engine.exec_code(session.runtime, session, state.paths, code, timeout))
    state.inflight[request_id] = task
    try:
        outcome = await task
    except asyncio.CancelledError:
        outcome = chromium.ExecOutcome("", "", None, int((time.time() - started_at) * 1000), cancelled=True)
    finally:
        state.inflight.pop(request_id, None)
        session.request_id = None
    if outcome.timed_out and session.engine == "camoufox":
        await _stop_session(state, session)
        state.restart_pending.add(session.name)
    else:
        sessions_mod.mark(session, "ready")
    sessions_mod.touch(state.table, session)
    page = await engine.observe(session.runtime) if session.runtime is not None else p.page_unavailable()
    found, artifact_warnings = artifacts.collect(session, outcome.stdout, started_at, now=p.now_iso)
    stdout, cut_out = p.truncate(outcome.stdout, p.STDOUT_CAP_BYTES)
    stderr, cut_err = p.truncate(outcome.stderr, p.STDERR_CAP_BYTES)
    warnings += [*outcome.warnings, *artifact_warnings, *(["output_truncated"] if cut_out or cut_err else [])]
    err = _outcome_error(outcome, session)
    if err is not None:
        state.last_error = err
    return p.result(
        request_id=request_id, op="exec", ok=err is None, session=sessions_mod.info(session), page=page,
        output={"stdout": stdout, "stderr": stderr, "exit_code": outcome.exit_code, "duration_ms": outcome.duration_ms},
        artifacts=found, warnings=warnings, err=err,
    )


async def op_cancel(state: State, request: dict[str, p.JsonValue]) -> p.Result:
    target = str(request["target_request_id"]) if "target_request_id" in request else ""
    task = state.inflight.pop(target, None)
    if task is None:
        return p.result(request_id=str(request["request_id"]), op="cancel", ok=True, data={"cancelled": False})
    task.cancel()
    return p.result(request_id=str(request["request_id"]), op="cancel", ok=True, data={"cancelled": True})


async def op_sessions(state: State, request: dict[str, p.JsonValue]) -> p.Result:
    listing: p.JsonValue = [dict(sessions_mod.info(s)) for s in state.table.sessions.values()]
    return p.result(request_id=str(request["request_id"]), op="sessions", ok=True, data={"sessions": listing})


async def op_session_stop(state: State, request: dict[str, p.JsonValue]) -> p.Result:
    name = str(request["session"]) if "session" in request else ""
    if name not in state.table.sessions:
        raise p.BrowserError(_invalid(f"unknown session {name!r}"))
    await _stop_session(state, state.table.sessions[name])
    return p.result(request_id=str(request["request_id"]), op="session_stop", ok=True, data={"stopped": name})


async def op_stop_all(state: State, request: dict[str, p.JsonValue]) -> p.Result:
    stopped = [s.name for s in state.table.sessions.values() if s.runtime is not None]
    for session in state.table.sessions.values():
        await _stop_session(state, session)
    return p.result(request_id=str(request["request_id"]), op="stop_all", ok=True, data={"stopped": stopped})


async def _idle_sweep(state: State) -> None:
    while True:
        await asyncio.sleep(IDLE_SWEEP_SECS)
        for session in sessions_mod.idle_sessions(state.table):
            logger.info("stopping idle session %s", session.name)
            await _stop_session(state, session)
        artifacts.prune(state.paths)
```

`State` gains `restart_pending: set[str] = dataclasses.field(default_factory=set)`. Register the handlers in `HANDLERS`: `"exec": op_exec, "cancel": op_cancel, "sessions": op_sessions, "session_stop": op_session_stop, "stop_all": op_stop_all`. In `serve()`, after the server starts, create the sweep task and keep it in `state.tasks` (`task.add_done_callback(state.tasks.discard)`). `shutdown()` cancels `state.tasks`, cancels every `state.inflight` task, then awaits `_stop_session` for every session. Note `op_exec` runs inside the connection handler: the `cancel` op arrives on a second connection and cancels the inflight task; the first handler catches `CancelledError` and answers `cancelled`. Because `cancel` cancels the engine task and not the handler, wrap the `await task` in the handler so the handler itself is never cancelled by a client action.

For `tp.cast(p.Mode | None, mode)`: `cast` to a concrete type is allowed by the conventions.

- [ ] **Step 4: Run the whole suite**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests -q`
Expected: PASS. If `test_idle_sweep_stops_a_ready_session` cannot patch `SESSION_IDLE_STOP_SECS` through two modules, change `sessions.idle_sessions` to take `idle_secs: int = p.SESSION_IDLE_STOP_SECS` as a parameter and patch the call in `serve._idle_sweep` instead.

- [ ] **Step 5: Run ruff and the convention guard**

Run: `cd agent && uv run ruff check skills/browser && uv run ruff format --check skills/browser && cd .. && uv run --project agent/core python scripts/check-conventions.py`
Expected: clean. Fix any complexity ceiling (`C901`/`PLR0913`) by splitting `op_exec` into `_run_exec` (spawn and wait) and `_finish_exec` (observe, artifacts, envelope).

- [ ] **Step 6: Commit**

```bash
git add agent/skills/browser/cli
git commit -m "feat(skills/browser): exec, cancel, session ops, idle sweep, and shutdown"
```

---

### Task 10: Doctor

**Files:**
- Create: `agent/skills/browser/cli/src/vesta_browser/doctor.py`
- Modify: `agent/skills/browser/cli/src/vesta_browser/serve.py` (register `doctor`)
- Test: `agent/skills/browser/cli/tests/test_doctor.py`

**Interfaces:**
- Produces: `async def report(state: State) -> dict[str, JsonValue]` with keys `daemon {pid, protocol_version, socket, log}`, `engines` (the `routes()` table plus `versions`), `sessions` (the `sessions` listing), `artifacts {root, bytes}`, `last_error`. Registered as op `doctor` in `serve.HANDLERS`.
- Versions are read by running each engine venv's python once: `<venv python> -c "import importlib.metadata as m; print(m.version('browser-use'), m.version('browser-harness'))"` and `... print(m.version('camoufox'), m.version('playwright'))`, plus `<chromium> --version`, each with a 10 s budget and `"unavailable"` on failure.

- [ ] **Step 1: Write the failing test**

```python
# agent/skills/browser/cli/tests/test_doctor.py
import asyncio
import sys

import pytest

from vesta_browser import serve
from vesta_browser.runtime_paths import load_paths

from .fakes import write_fakes


def test_doctor_reports_daemon_engines_sessions_and_disk(tmp_path):
    env = write_fakes(tmp_path / "bin")
    env["VESTA_BROWSER_CAMOUFOX_PYTHON"] = sys.executable
    paths = load_paths(env, tmp_path)

    async def run():
        server = asyncio.create_task(serve.serve(paths))
        for _ in range(100):
            if paths.socket.exists():
                break
            await asyncio.sleep(0.02)
        try:
            return await serve.request(paths, {"version": 1, "op": "doctor", "request_id": "d"})
        finally:
            server.cancel()
            with pytest.raises(asyncio.CancelledError):
                await server

    res = asyncio.run(run())
    data = res["data"]
    assert data["daemon"]["protocol_version"] == 1 and data["daemon"]["socket"] == str(paths.socket)
    assert data["engines"]["routes"]["standard"]["ready"] is True
    assert data["engines"]["routes"]["stealth"]["ready"] is False
    assert data["engines"]["versions"]["camoufox"] == "unavailable"  # the test interpreter has no camoufox
    assert data["sessions"] == [] and data["artifacts"]["bytes"] == 0 and data["last_error"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_doctor.py -q`
Expected: FAIL (`doctor` unknown op).

- [ ] **Step 3: Write `doctor.py` and register it**

```python
"""One report of everything the daemon knows: binaries, versions, sessions, artifacts, and the last error."""

from __future__ import annotations

import asyncio
import os
import pathlib as pl

from . import protocol as p
from . import sessions as sessions_mod
from .runtime_paths import Paths
from .serve import State, routes

VERSION_PROBE_TIMEOUT_SECS = 10


async def _probe(argv: list[str]) -> str:
    try:
        process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(process.communicate(), VERSION_PROBE_TIMEOUT_SECS)
    except (OSError, TimeoutError):
        return "unavailable"
    text = out.decode(errors="replace").strip()
    return text if process.returncode == 0 and text else "unavailable"


async def versions(paths: Paths) -> dict[str, p.JsonValue]:
    metadata = "import importlib.metadata as m; print(' '.join(m.version(n) for n in {names}))"
    chromium, standard, stealth = await asyncio.gather(
        _probe([str(paths.chromium_exe), "--version"]),
        _probe([str(paths.browser_use_bin.parent / "python"), "-c", metadata.format(names=["browser-use", "browser-harness"])]),
        _probe([str(paths.camoufox_python), "-c", metadata.format(names=["camoufox", "playwright"])]),
    )
    bu, bh = (standard.split() + ["unavailable", "unavailable"])[:2] if standard != "unavailable" else ("unavailable", "unavailable")
    cf, pw = (stealth.split() + ["unavailable", "unavailable"])[:2] if stealth != "unavailable" else ("unavailable", "unavailable")
    return {"chromium": chromium, "browser-use": bu, "browser-harness": bh, "camoufox": cf, "playwright": pw, "camoufox_browser": paths.camoufox_exe.parent.name}


def _tree_bytes(root: pl.Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) if root.is_dir() else 0


async def report(state: State) -> dict[str, p.JsonValue]:
    paths = state.paths
    return {
        "daemon": {"pid": os.getpid(), "protocol_version": p.PROTOCOL_VERSION, "socket": str(paths.socket), "log": str(paths.log)},
        "engines": {**routes(paths), "versions": await versions(paths)},
        "sessions": [dict(sessions_mod.info(s)) for s in state.table.sessions.values()],
        "artifacts": {"root": str(paths.artifacts), "bytes": await asyncio.to_thread(_tree_bytes, paths.artifacts)},
        "last_error": state.last_error,
    }
```

`doctor.py` imports `serve`, so `serve` cannot import `doctor` at module top without a cycle. Register the op from `cli.py` instead: `serve.HANDLERS["doctor"] = lambda state, req: doctor.op_doctor(state, str(req["request_id"]))` is still a hidden edge. The DAG-clean shape: move `State` and `routes` into a new `daemon_state.py` (imported by both `serve` and `doctor`), and let `serve` import `doctor` and register `"doctor": doctor.op_doctor`. Add to `doctor.py`:

```python
async def op_doctor(state: State, request: dict[str, p.JsonValue]) -> p.Result:
    return p.result(request_id=str(request["request_id"]), op="doctor", ok=True, data=await report(state))
```

- [ ] **Step 4: Run the suite**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/skills/browser/cli
git commit -m "feat(skills/browser): doctor report"
```

---

### Task 11: The `browser` CLI

**Files:**
- Modify: `agent/skills/browser/cli/src/vesta_browser/cli.py`
- Test: `agent/skills/browser/cli/tests/test_cli.py`

**Interfaces:**
- Commands: `exec --session <name> [--stealth] [--timeout <secs>]` (stdin), `daemon <verb>`, `serve`, `doctor`, `engines`, `sessions`, `session stop <name>`, `stop-all`, `handover start|status|stop` (PR 1 sends the RPC; the daemon answers `invalid_request` until PR 2 registers the ops).
- Produces: `main(argv=None) -> int`; `send(paths, payload, timeout) -> Result` (sync socket client); `emit(result) -> int` (stdout on ok, stderr otherwise, returns the exit code).
- Every RPC command mints `request_id = f"r_{uuid4().hex[:12]}"`. `exec` installs SIGINT/SIGTERM handlers that send `cancel` for that id, then exits 1 with a `cancelled` envelope.

- [ ] **Step 1: Write the failing tests**

```python
# agent/skills/browser/cli/tests/test_cli.py
import io
import json
import subprocess
import sys
import threading
import time

import pytest

from vesta_browser import cli, serve
from vesta_browser.runtime_paths import load_paths


def test_daemon_down_is_a_loud_error_on_stderr(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(1)"))
    code = cli.main(["exec", "--session", "default"])
    out, err = capsys.readouterr()
    assert code == 1 and out == ""
    envelope = json.loads(err)
    assert envelope["ok"] is False and envelope["error"]["code"] == "daemon_down"
    assert envelope["error"]["suggested_action"] == "run: browser daemon start"


def test_exec_sends_the_request_and_prints_one_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = load_paths({}, tmp_path)
    seen = {}

    def fake_send(_paths, payload, timeout):
        seen.update(payload)
        return serve.p.result(request_id=payload["request_id"], op="exec", ok=True, data={"echo": True})

    monkeypatch.setattr(cli, "send", fake_send)
    monkeypatch.setattr(sys, "stdin", io.StringIO("new_tab('x')\n"))
    code = cli.main(["exec", "--session", "research", "--stealth", "--timeout", "42"])
    out, err = capsys.readouterr()
    assert code == 0 and err == "" and out.count("\n") == 1
    assert seen["op"] == "exec" and seen["session"] == "research" and seen["mode"] == "stealth"
    assert seen["timeout_s"] == 42 and seen["code"] == "new_tab('x')\n" and seen["version"] == 1


def test_exec_without_stealth_sends_a_null_mode(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = {}
    monkeypatch.setattr(cli, "send", lambda _p, payload, _t: seen.update(payload) or serve.p.result(request_id="x", op="exec", ok=True))
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(1)"))
    cli.main(["exec"])
    assert seen["mode"] is None and seen["session"] == "default" and seen["timeout_s"] == 120


def test_failed_result_goes_to_stderr_with_exit_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    err = serve.p.error("execution_failed", "execution", "boom", retryable=False, suggested_action="fix")
    monkeypatch.setattr(cli, "send", lambda _p, payload, _t: serve.p.result(request_id="x", op="exec", ok=False, err=err))
    monkeypatch.setattr(sys, "stdin", io.StringIO("print(1)"))
    code = cli.main(["exec"])
    out, stderr = capsys.readouterr()
    assert code == 1 and out == "" and json.loads(stderr)["error"]["code"] == "execution_failed"


@pytest.mark.parametrize(
    ("argv", "op", "extra"),
    [
        (["doctor"], "doctor", {}),
        (["engines"], "engines", {}),
        (["sessions"], "sessions", {}),
        (["session", "stop", "research"], "session_stop", {"session": "research"}),
        (["stop-all"], "stop_all", {}),
        (["handover", "start", "--url", "https://x", "--session", "s", "--stealth", "--minutes", "10"], "handover_start", {"url": "https://x", "session": "s", "mode": "stealth", "minutes": 10}),
        (["handover", "status"], "handover_status", {}),
        (["handover", "stop"], "handover_stop", {}),
    ],
)
def test_every_rpc_command_maps_to_its_op(monkeypatch, tmp_path, argv, op, extra):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = {}
    monkeypatch.setattr(cli, "send", lambda _p, payload, _t: seen.update(payload) or serve.p.result(request_id="x", op=op, ok=True))
    assert cli.main(argv) == 0
    assert seen["op"] == op and all(seen[k] == v for k, v in extra.items())


def test_usage_on_no_args_and_unknown_command(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cli.main([]) == 1
    assert cli.main(["dance"]) == 1


def test_sigint_during_exec_sends_cancel(tmp_path, monkeypatch):
    """Runs the real CLI as a subprocess against a stub daemon that holds the exec until it sees cancel."""
    paths = load_paths({}, tmp_path)
    paths.root.mkdir(parents=True)
    import socket

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(paths.socket))
    server.listen(2)
    seen_ops = []

    def stub():
        first, _ = server.accept()
        first_req = json.loads(first.makefile("rb").readline())
        seen_ops.append(first_req["op"])
        second, _ = server.accept()
        second_req = json.loads(second.makefile("rb").readline())
        seen_ops.append(second_req["op"])
        second.sendall(json.dumps(serve.p.result(request_id="c", op="cancel", ok=True)).encode() + b"\n")
        second.close()
        first.sendall(json.dumps(serve.p.result(request_id=first_req["request_id"], op="exec", ok=False)).encode() + b"\n")
        first.close()

    threading.Thread(target=stub, daemon=True).start()
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; from vesta_browser.cli import main; sys.exit(main(['exec']))"],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(cli.__file__).rsplit("/vesta_browser", 1)[0]},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    proc.stdin.write("SLEEP")
    proc.stdin.close()
    time.sleep(0.5)
    proc.send_signal(2)
    _, err = proc.communicate(timeout=10)
    assert proc.returncode == 1 and seen_ops == ["exec", "cancel"]
    assert json.loads(err)["error"]["code"] == "cancelled"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_cli.py -q`
Expected: FAIL.

- [ ] **Step 3: Write `cli.py`**

```python
"""The `browser` command: one JSON request over the daemon socket, one JSON line back.

Every browser decision lives in the daemon. This client parses arguments, reads the program from
stdin, sends one request, and prints one line: stdout on success, stderr on failure, exit 1.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib as pl
import signal
import socket
import sys
import threading
import uuid

from . import lifecycle, protocol as p, serve
from .runtime_paths import Paths, load_paths

USAGE = """Usage:
  browser exec --session <name> [--stealth] [--timeout <secs>]   # Python on stdin
  browser daemon start|stop|restart|status
  browser doctor | engines | sessions | session stop <name> | stop-all
  browser handover start [--url <url>] [--session <name>] [--stealth] [--minutes <n>]
  browser handover status | stop"""
RPC_TIMEOUT_SLACK_SECS = 30


def _request_id() -> str:
    return f"r_{uuid.uuid4().hex[:12]}"


def send(paths: Paths, payload: dict[str, p.JsonValue], timeout: float) -> p.Result:
    """One request, one reply. A socket that is absent or refuses is `daemon_down`."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(paths.socket))
            sock.sendall((json.dumps(payload) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(1 << 16)
                if not chunk:
                    break
                data += chunk
    except OSError as exc:
        err = p.error("daemon_down", "validation", f"browser daemon not reachable at {paths.socket}: {exc}", retryable=True, suggested_action="run: browser daemon start")
        return p.result(request_id=str(payload["request_id"]), op=str(payload["op"]), ok=False, err=err)
    return json.loads(data)


def emit(result: p.Result) -> int:
    line = json.dumps(result)
    if result["ok"]:
        print(line)
        return 0
    print(line, file=sys.stderr)
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browser", usage=USAGE, add_help=True)
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("exec")
    run.add_argument("--session", default=p.DEFAULT_SESSION)
    run.add_argument("--stealth", action="store_true")
    run.add_argument("--timeout", type=int, default=p.EXEC_TIMEOUT_DEFAULT_SECS)
    daemon = sub.add_parser("daemon")
    daemon.add_argument("verb", nargs="?", default="")
    sub.add_parser("serve")
    for name in ("doctor", "engines", "sessions", "stop-all"):
        sub.add_parser(name)
    session = sub.add_parser("session")
    session.add_argument("verb", choices=["stop"])
    session.add_argument("name")
    handover = sub.add_parser("handover")
    handover.add_argument("verb", choices=["start", "status", "stop"])
    handover.add_argument("--url", default=None)
    handover.add_argument("--session", default=p.DEFAULT_SESSION)
    handover.add_argument("--stealth", action="store_true")
    handover.add_argument("--minutes", type=int, default=None)
    return parser


def _exec(paths: Paths, args: argparse.Namespace) -> int:
    request_id = _request_id()
    payload: dict[str, p.JsonValue] = {
        "version": p.PROTOCOL_VERSION, "op": "exec", "request_id": request_id, "session": args.session,
        "mode": "stealth" if args.stealth else None, "timeout_s": args.timeout, "code": sys.stdin.read(),
    }
    cancelled = threading.Event()

    def on_signal(_signum: int, _frame: object) -> None:
        cancelled.set()
        send(paths, {"version": p.PROTOCOL_VERSION, "op": "cancel", "request_id": _request_id(), "target_request_id": request_id}, 5)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    result = send(paths, payload, args.timeout + RPC_TIMEOUT_SLACK_SECS)
    if cancelled.is_set():
        err = p.error("cancelled", "execution", "interrupted by the caller", retryable=False, suggested_action="rerun when ready")
        result = p.result(request_id=request_id, op="exec", ok=False, session=result["session"], err=err)
    return emit(result)


def _rpc(paths: Paths, op: str, **fields: p.JsonValue) -> int:
    return emit(send(paths, {"version": p.PROTOCOL_VERSION, "op": op, "request_id": _request_id(), **fields}, RPC_TIMEOUT_SLACK_SECS))


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    if not args_list:
        print(USAGE, file=sys.stderr)
        return 1
    try:
        args = _parser().parse_args(args_list)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1
    paths = load_paths(os.environ, pl.Path.home())
    if args.command == "daemon":
        return lifecycle.daemon_cmd(args.verb, paths)
    if args.command == "serve":
        return serve.main()
    if args.command == "exec":
        return _exec(paths, args)
    if args.command == "session":
        return _rpc(paths, "session_stop", session=args.name)
    if args.command == "handover":
        if args.verb == "start":
            return _rpc(paths, "handover_start", url=args.url, session=args.session, mode="stealth" if args.stealth else None, minutes=args.minutes)
        return _rpc(paths, f"handover_{args.verb}")
    return _rpc(paths, args.command.replace("-", "_"))
```

`argparse` prints its own usage on an unknown command and raises `SystemExit(2)`; the test expects 1, so catch it as shown and return 1. Keep `print(USAGE, file=sys.stderr)` for the no-args case.

- [ ] **Step 4: Run the suite, ruff, and the contract row again**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests -q && uv run pytest tests/test_daemon_contract.py -k browser -q && uv run ruff check skills/browser`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add agent/skills/browser/cli
git commit -m "feat(skills/browser): thin browser CLI over the daemon socket"
```

---

### Task 12: Engine installer and image layer

**Files:**
- Create: `agent/skills/browser/install-engines.sh`
- Create: `agent/skills/browser/cli/src/vesta_browser/camoufox_install.py` (standalone, stdlib only, no package imports)
- Modify: `vestad/Dockerfile` (apt layer after line 49; `RUN` after `COPY agent/ ./agent/`)
- Test: `agent/skills/browser/cli/tests/test_camoufox_install.py`

**Interfaces:**
- `camoufox_install.py`: `CAMOUFOX_RELEASE_TAG`, `CAMOUFOX_ASSETS` (moved verbatim from the deleted `launcher.py:32-38`), `INSTALL_ROOT = Path("/opt/camoufox")`; `install(root: Path = INSTALL_ROOT, arch: str = platform.machine()) -> Path` (idempotent: returns `<root>/<tag>/camoufox` when present, else downloads to `<root>/.<asset>.part`, verifies sha256, extracts preserving exec bits into `<root>/.<tag>.staging`, runs `repair_search_stub`, renames to `<root>/<tag>`); `repair_search_stub(home: Path) -> None` (moved verbatim from `launcher.py`, including `_BROKEN_SEARCH_STUB` and `_REPAIRED_SEARCH_STUB`); `main() -> int` prints `{"installed": "<path>"}`.
- `runtime_paths.CAMOUFOX_RELEASE_TAG` must equal `camoufox_install.CAMOUFOX_RELEASE_TAG`; a test pins it.

- [ ] **Step 1: Write the failing tests**

```python
# agent/skills/browser/cli/tests/test_camoufox_install.py
import hashlib
import io
import json
import pathlib as pl
import subprocess
import sys
import zipfile

import pytest

from vesta_browser import camoufox_install as ci
from vesta_browser import runtime_paths

SCRIPT = pl.Path(ci.__file__)


def _zip_bytes(with_exec_bit: bool) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("camoufox")
        info.external_attr = (0o755 if with_exec_bit else 0o644) << 16
        z.writestr(info, "#!/bin/sh\n")
        z.writestr("properties.json", "{}")
    return buf.getvalue()


def test_tags_agree_between_installer_and_runtime_paths():
    assert ci.CAMOUFOX_RELEASE_TAG == runtime_paths.CAMOUFOX_RELEASE_TAG


def test_install_is_a_no_op_when_the_tag_is_present(tmp_path):
    home = tmp_path / ci.CAMOUFOX_RELEASE_TAG
    home.mkdir()
    (home / "camoufox").write_text("")
    assert ci.install(root=tmp_path, arch="x86_64", download=lambda url, dest: pytest.fail("downloaded")) == home / "camoufox"


def test_install_downloads_verifies_extracts_and_publishes(tmp_path, monkeypatch):
    payload = _zip_bytes(with_exec_bit=True)
    monkeypatch.setitem(ci.CAMOUFOX_ASSETS, "x86_64", ("asset.zip", hashlib.sha256(payload).hexdigest()))
    urls = []

    def fake_download(url, dest):
        urls.append(url)
        pl.Path(dest).write_bytes(payload)

    exe = ci.install(root=tmp_path, arch="x86_64", download=fake_download)
    assert exe == tmp_path / ci.CAMOUFOX_RELEASE_TAG / "camoufox" and exe.stat().st_mode & 0o111
    assert urls == [f"{ci.RELEASE_DOWNLOAD_URL}/{ci.CAMOUFOX_RELEASE_TAG}/asset.zip"]
    assert not list(tmp_path.glob(".*"))  # no .part or .staging left behind


def test_sha_mismatch_refuses_and_leaves_no_install(tmp_path, monkeypatch):
    payload = _zip_bytes(with_exec_bit=True)
    monkeypatch.setitem(ci.CAMOUFOX_ASSETS, "x86_64", ("asset.zip", "0" * 64))
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        ci.install(root=tmp_path, arch="x86_64", download=lambda url, dest: pl.Path(dest).write_bytes(payload))
    assert not (tmp_path / ci.CAMOUFOX_RELEASE_TAG).exists()


def test_unsupported_arch_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match="unsupported architecture"):
        ci.install(root=tmp_path, arch="mips")


def test_repair_search_stub_is_idempotent(tmp_path):
    omni = tmp_path / "omni.ja"
    with zipfile.ZipFile(omni, "w") as z:
        z.writestr(ci._OMNI_SEARCH_SELECTOR, "prefix " + ci._BROKEN_SEARCH_STUB + " suffix")
    ci.repair_search_stub(tmp_path)
    ci.repair_search_stub(tmp_path)
    with zipfile.ZipFile(omni) as z:
        assert z.read(ci._OMNI_SEARCH_SELECTOR).decode() == "prefix " + ci._REPAIRED_SEARCH_STUB + " suffix"


def test_script_runs_standalone_under_the_system_python(tmp_path):
    """install-engines.sh runs this file by path with /usr/bin/python3, so it must not import the package."""
    home = tmp_path / ci.CAMOUFOX_RELEASE_TAG
    home.mkdir()
    (home / "camoufox").write_text("")
    result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0 and json.loads(result.stdout) == {"installed": str(home / "camoufox")}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_camoufox_install.py -q`
Expected: FAIL, module not found.

- [ ] **Step 3: Write `camoufox_install.py`**

Move from the deleted `launcher.py` (use `git show HEAD~N:agent/skills/browser/cli/src/vesta_browser/launcher.py` from the Task 2 parent commit): `CAMOUFOX_RELEASE_TAG`, `CAMOUFOX_ASSETS`, `RELEASE_DOWNLOAD_URL`, `DOWNLOAD_TIMEOUT_S`, `DOWNLOAD_CHUNK`, `_verify_sha256`, `_download`, `_extract_preserving_mode`, `_OMNI_SEARCH_SELECTOR`, `_BROKEN_SEARCH_STUB`, `_REPAIRED_SEARCH_STUB`, `repair_search_stub`. Then:

```python
"""Installs the pinned Camoufox bundle under /opt/camoufox/<tag>/. Standalone: run by path with the system python.

The Dockerfile runs it for fresh images and the browser-daemon migration runs it on the fleet,
because a fleet upgrade never reruns the Dockerfile. Idempotent: an installed tag is left alone.
"""

INSTALL_ROOT = pl.Path("/opt/camoufox")
Downloader = tp.Callable[[str, pl.Path], None]


def _asset_for_arch(arch: str) -> tuple[str, str]:
    if arch not in CAMOUFOX_ASSETS:
        raise RuntimeError(f"unsupported architecture {arch!r}; supported: {sorted(CAMOUFOX_ASSETS)}")
    return CAMOUFOX_ASSETS[arch]


def install(root: pl.Path = INSTALL_ROOT, arch: str = platform.machine(), download: Downloader = _download) -> pl.Path:
    home = root / CAMOUFOX_RELEASE_TAG
    exe = home / "camoufox"
    if exe.is_file():
        # LEGACY(remove-when: CAMOUFOX_RELEASE_TAG moves past v150.0.2-beta.25): heals bundles
        # extracted before the search-stub repair shipped; a new tag always extracts fresh.
        repair_search_stub(home)
        return exe
    asset_name, expected_sha = _asset_for_arch(arch)
    root.mkdir(parents=True, exist_ok=True)
    part = root / f".{asset_name}.part"
    staging = root / f".{CAMOUFOX_RELEASE_TAG}.staging"
    try:
        download(f"{RELEASE_DOWNLOAD_URL}/{CAMOUFOX_RELEASE_TAG}/{asset_name}", part)
        _verify_sha256(part, expected_sha)
        if staging.exists():
            shutil.rmtree(staging)
        _extract_preserving_mode(part, staging)
        repair_search_stub(staging)
        staging.replace(home)
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
    return exe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pl.Path, default=INSTALL_ROOT)
    args = parser.parse_args()
    print(json.dumps({"installed": str(install(root=args.root))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the installer tests**

Run: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests/test_camoufox_install.py -q`
Expected: PASS.

- [ ] **Step 5: Write `install-engines.sh`**

```bash
#!/usr/bin/env bash
# Installs the two browser engines the browser daemon drives: Debian's chromium and the pinned
# Camoufox bundle. Run by the Dockerfile for fresh images and by the browser-daemon migration on
# the fleet (fleet upgrades never rerun the Dockerfile). Safe to rerun.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v chromium >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends chromium
  rm -rf /var/lib/apt/lists/*
fi

python3 "$SKILL_DIR/cli/src/vesta_browser/camoufox_install.py"
```

Run: `shellcheck -S warning agent/skills/browser/install-engines.sh && chmod +x agent/skills/browser/install-engines.sh`

- [ ] **Step 6: Add the Dockerfile layers**

After the handover apt block (line 49) add:

```dockerfile
# ── browser daemon engines: Debian chromium for the standard route, the pinned Camoufox bundle for
# stealth. install-engines.sh is the one owner (the migration runs the same script on the fleet).
RUN apt-get update && apt-get install -y --no-install-recommends chromium && \
    rm -rf /var/lib/apt/lists/*
```

After `COPY agent/ ./agent/` (line 92) add:

```dockerfile
RUN /root/agent/skills/browser/install-engines.sh
```

Verify: `docker build -f vestad/Dockerfile -t vesta:local . && docker run --rm vesta:local sh -c 'chromium --version && ls /opt/camoufox/*/camoufox'` (ask the user before building on the shared host; a build pulls ~200 MB).

- [ ] **Step 7: Commit**

```bash
git add agent/skills/browser/install-engines.sh agent/skills/browser/cli vestad/Dockerfile
git commit -m "feat(skills/browser): pinned engine installer for the image and the fleet"
```

---

### Task 13: Repo docs and attribution

**Files:**
- Modify: `AGENTS.md` (the two places that list the four public services: the Auth paragraph naming "the whatsapp QR link page, `file-host`, the `agentmail` webhook, and the browser handover page", and the daemon-contract paragraph listing `--public` for "`file-host`, the `agentmail` webhook, the whatsapp link page, and the browser handover page"); the Skills bullet gains one sentence on the browser daemon.
- Modify: `agent/skills/browser/ATTRIBUTION.md`
- Modify: `agent/skills/browser/SKILL.md` (interim banner only; PR 3 rewrites it)

- [ ] **Step 1: Edit AGENTS.md**

Remove "and the browser handover page" / "the browser handover page" from both public-service lists (three public services remain). In the Skills bullet, after the sentence ending "the only MCP server is the agent's own native tool registry (`core/tools.py`), exposed in-process via `create_sdk_mcp_server`.", add: "The browser skill is one per-agent daemon (`browser daemon start`, `agent/skills/browser/cli/`) that owns sessions, both engines (Chromium through browser-use and Browser Harness over CDP, Camoufox through Playwright Firefox in a supervised worker), artifacts, and handover; Vesta and internal skill CLIs reach it only through `browser exec` and its sibling commands, never a browser library."

- [ ] **Step 2: Edit ATTRIBUTION.md**

Below the existing browser-harness notice add:

```markdown
## Runtime dependencies

- Browser Use (`browser-use` 0.13.10, MIT, https://github.com/browser-use/browser-use) and Browser Harness (`browser-harness` 0.1.13, MIT, https://github.com/browser-use/browser-harness) run the Chromium route in `engines/chromium/`.
- Camoufox Python library (`camoufox` 0.5.6b1, MIT, https://github.com/daijro/camoufox/tree/main/pythonlib) runs the stealth route in `engines/camoufox/`; the Camoufox browser bundle installed at `/opt/camoufox/<tag>/` is Mozilla Public License 2.0 (https://github.com/daijro/camoufox/blob/main/LICENSE).
```

- [ ] **Step 3: Interim SKILL.md banner**

Prepend, directly under the frontmatter, one paragraph: "The browser runtime is a daemon now: `browser daemon start`, then `browser exec --session <name> [--stealth]` with Python on stdin (helpers: `new_tab`, `goto_url`, `page_info`, `js`, `click_at_xy`, `fill_input`, `capture_screenshot`, ...). The command reference below is being rewritten; commands it names other than `doctor`, `sessions`, `stop-all`, and `handover` no longer exist." Use the `vesta-prompt-guide` skill for the wording. This banner is replaced wholesale by PR 3.

- [ ] **Step 4: Run the full check set**

Run: `./check.sh guards && ./check.sh agent`
Expected: green. `check.sh agent` picks up `skills/browser/cli/tests` automatically.

- [ ] **Step 5: Commit and open the PR**

```bash
git add AGENTS.md agent/skills/browser/ATTRIBUTION.md agent/skills/browser/SKILL.md
git commit -m "docs: browser daemon ownership, attribution, and interim skill banner"
git push -u origin feat/browser-daemon
gh pr create --title "feat(skills/browser): browser daemon with chromium and camoufox executors" --body-file <(printf '%s\n' "Implements PR 1 of docs/superpowers/specs/2026-09-04-browser-daemon-design.md: one per-agent browser daemon ..." "" "🤖 Generated with [Claude Code](https://claude.com/claude-code)")
```

Write the PR body from the spec's Decisions section; state that PR 2 (handover) and PR 3 (callers, skill, migration) must land before the next release.

---

## Self-review notes

- Spec coverage for PR 1: layout (Tasks 1, 2), CLI contract (11), protocol and envelope (2, 9), validation (9), sessions and pinning (4, 9), Chromium route (6), Camoufox route (7, 8), portable helpers (7, pinned equal to `protocol.PORTABLE_HELPERS`), artifacts (5), timeouts and cancel (6, 8, 9, 11), idle stop (9), doctor and engines (3, 10), daemon contract row and lifecycle (3), packaging (1, 12), repo integration (2, 13). Deferred to PR 2: handover ops. Deferred to PR 3: SKILL.md/SETUP.md rewrite, maps, microsoft, flights, MEMORY.md, the migration, `daemons.sh` line.
- Type consistency: `ExecOutcome` is defined once in `chromium.py` and imported by `camoufox.py` and `serve.py`; `now_iso` lives in `protocol.py` after Task 6; `State` and `routes` move to `daemon_state.py` in Task 10 (update Task 3's tests to import `serve.request`/`serve.serve` only, which they already do).
- Known judgment calls for the implementer: `tp.Any` in `worker.py` for Playwright objects (replace with narrow `Protocol`s if lint refuses); `assert` on `process.stdin`/`stdout` (replace with explicit raises if `S101` is enforced); the `exec` call in the worker may need an `S102` tune in `agent/ruff.toml` with a one-line justification.
