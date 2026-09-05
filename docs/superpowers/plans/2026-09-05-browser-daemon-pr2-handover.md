# Browser Daemon (PR 2: private handover) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hand a session's real browser (Chromium or Camoufox) to the user through a private, key-protected noVNC page, orchestrated by the browser daemon, resuming headless automation on the same profile when the user is done.

**Architecture:** Three new modules under `cli/src/vesta_browser/`: `gateway.py` (the vestad helper scripts as async subprocess calls: register, deregister, mint, list, revoke), `display.py` (Xvfb display claim, openbox, x11vnc with the shm fallback, websockify, the noVNC webroot), and `handover.py` (the orchestration, the expiry task, status). The engines gain a headed launch. `serve.py` registers `handover_start|status|stop`, protects `handed_over` sessions from stop paths, and tears a live handover down on shutdown. The page is a static asset extracted from the deleted runtime.

**Tech Stack:** Python 3.11+ stdlib (asyncio subprocesses, sockets), Xvfb, openbox, x11vnc, websockify + noVNC (`/usr/share/novnc`), vestad's `register-service` / `deregister-service` / `service-key` scripts.

**Spec:** `docs/superpowers/specs/2026-09-04-browser-daemon-design.md` (section Handover, plus Daemon protocol and Sessions).

**Base:** branch `feat/browser-handover`, stacked on `feat/browser-daemon` (PR #2391). Worktree `/home/emi/vesta-wt-browser-spec`.

## Global Constraints

- Everything in plan 1's Global Constraints still binds (Python conventions, async rules, comment caps, one JSON line per command, daemon contract, naming, no spaced dashes, "Vesta" for the agent). Commit trailers: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01VWMfwWdkJHjAXDbAJjv5Kd`.
- Handover registers the `browser` service **private** (`register-service browser`, never `--public`) and shares only a path-keyed URL: `$VESTAD_PUBLIC_URL/agents/$AGENT_NAME/browser/k/<key>/handover.html`. The daemon mints the key (`service-key mint browser --label browser-handover-<id> --ttl <lifetime secs>`) and revokes it by id (found through `service-key list browser` by label) on stop, expiry, failure, and shutdown.
- `register-service <name>` prints the port vestad allocated; websockify binds **that** port on `0.0.0.0` (vestad reaches the container over its network; a `127.0.0.1` bind is invisible to the proxy).
- Constants: `HANDOVER_DEFAULT_MINUTES = 30`, `HANDOVER_MAX_MINUTES = 240`, `SCREEN_W, SCREEN_H = 1280, 800`, `DISPLAY_FIRST, DISPLAY_LAST = 99, 198`, `VNC_PORT_FIRST = 5900`, `XVFB_READY_TIMEOUT_SECS = 5`, `X11VNC_READY_TIMEOUT_SECS = 10`, `X11VNC_SETTLE_SECS = 0.4`, `WEB_READY_TIMEOUT_SECS = 10`, `GATEWAY_TIMEOUT_SECS = 35`, `HANDOVER_BINARIES = ("Xvfb", "x11vnc", "websockify", "openbox")`.
- Session state `handed_over` while a handover is live; `op_exec` already refuses it (`handover_in_use`); this plan makes `_stop_session` refuse it too unless `force`. One handover at a time per daemon.
- Handover status data: `{state, handover_id, session, engine, user_url, expires_at}` with `state ∈ inactive | starting | live | stopping | expired | failed`; `live` only when Xvfb serves its socket, x11vnc and websockify ports answer, and the headed browser process is alive, all checked at status time.
- The daemon never captures a screenshot during a handover. Headed Chromium keeps `--remote-debugging-port=0` so `observe()` still works after resume; the resume is `_stop_session(force=True)` followed by the next exec's ordinary start.
- Paths (all env-overridable for tests): `Paths.novnc_dir` (`VESTA_BROWSER_NOVNC_DIR`, default `/usr/share/novnc`), `Paths.x11_socket_dir` (`VESTA_BROWSER_X11_DIR`, default `/tmp/.X11-unix`), `Paths.handover_web = root / "handover-web"`, `Paths.assets = SKILL_DIR / "cli/src/vesta_browser/assets/handover"`. `AGENT_NAME` and `VESTAD_PUBLIC_URL` come from the environment; a missing `VESTAD_PUBLIC_URL` fails the handover with `handover_failed` naming it.
- Test commands as in plan 1 (`uv run --project skills/browser/cli pytest skills/browser/cli/tests -q`, ruff, `./check.sh guards`, the contract row). Fakes for every external binary live in `cli/tests/fakes.py`; no test needs a real X server, VNC, or vestad.

---

## File structure

```
agent/skills/browser/cli/src/vesta_browser/
  runtime_paths.py      Task 1: novnc_dir, x11_socket_dir, handover_web, assets
  gateway.py            Task 1: register_service, deregister_service, mint_key, find_key_id, revoke_key
  display.py            Task 2: claim_display, start_openbox, start_x11vnc, start_websockify, build_webroot, port helpers, readiness()
  assets/handover/handover.html   Task 2: the noVNC page, extracted from git history (2e689694 handover.py `_PAGE_TEMPLATE`)
  chromium.py           Task 3: start(session, paths, *, headed: HeadedDisplay | None = None)
  camoufox.py           Task 3: start(..., headed: HeadedDisplay | None = None): user.js prefs, fit_to_screen config, DISPLAY env
  runtimes.py           Task 3: HeadedDisplay dataclass (display: str, width: int, height: int)
  handover.py           Task 4: Handover dataclass, start/stop/status/expiry, op_handover_start|status|stop
  daemon_state.py       Task 4: State.handover: Handover | None
  serve.py              Task 4: register the three ops; _stop_session refuses handed_over; shutdown tears a live handover down
  doctor.py             Task 5: `handover` readiness block (binaries + noVNC + live state)
cli/tests/
  fakes.py              Task 2: fake Xvfb, openbox, x11vnc, websockify, register-service, deregister-service, service-key
  test_gateway.py, test_display.py, test_engines_headed.py, test_handover.py, test_doctor.py (extended)
```

---

### Task 1: Gateway helpers and paths

**Files:**
- Modify: `cli/src/vesta_browser/runtime_paths.py`
- Create: `cli/src/vesta_browser/gateway.py`
- Test: `cli/tests/test_gateway.py`, `cli/tests/test_runtime_paths.py` (extend)

**Interfaces:**
- `Paths` gains `novnc_dir`, `x11_socket_dir`, `handover_web`, `assets`.
- `gateway.py`: `GATEWAY_TIMEOUT_SECS = 35`; `class GatewayError(Exception)`; `async def register_service(name: str) -> int` (returns the port); `async def deregister_service(name: str) -> None` (idempotent, never raises on a 404); `async def mint_key(service: str, label: str, ttl_secs: int) -> str` (the secret); `async def find_key_id(service: str, label: str) -> str | None` (parses `service-key list` JSON `{"keys": [{"id", "label", ...}]}`); `async def revoke_key(service: str, key_id: str) -> None`. All run the scripts by name on PATH with `asyncio.create_subprocess_exec`, stdout/stderr captured, `GATEWAY_TIMEOUT_SECS` budget; a non-zero exit raises `GatewayError(stderr)`.

- [ ] **Step 1: Failing tests**

```python
# cli/tests/test_gateway.py
import asyncio
import json
import pathlib as pl
import stat
import sys

import pytest

from vesta_browser import gateway

FAKE_SERVICE_KEY = f"""#!{sys.executable}
import json, os, sys
log = pl = None
cmd = sys.argv[1]
service = sys.argv[2]
state = os.environ["FAKE_KEYS"]
keys = json.load(open(state)) if os.path.exists(state) else []
if cmd == "mint":
    label = sys.argv[sys.argv.index("--label") + 1]
    ttl = sys.argv[sys.argv.index("--ttl") + 1]
    keys.append({{"id": f"id{{len(keys) + 1}}", "label": label, "ttl": int(ttl)}})
    json.dump(keys, open(state, "w"))
    print(f"secret-{{label}}")
elif cmd == "list":
    print(json.dumps({{"keys": [{{"id": k["id"], "label": k["label"]}} for k in keys]}}))
elif cmd == "revoke":
    keys = [k for k in keys if k["id"] != sys.argv[3]]
    json.dump(keys, open(state, "w"))
else:
    print("usage", file=sys.stderr); sys.exit(2)
"""

FAKE_REGISTER = f"""#!{sys.executable}
import os, sys
open(os.environ["FAKE_REGISTER_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")
print(os.environ["FAKE_PORT"])
"""

FAKE_DEREGISTER = f"""#!{sys.executable}
import os, sys
open(os.environ["FAKE_REGISTER_LOG"], "a").write("deregister " + sys.argv[1] + "\\n")
"""


def _script(bin_dir: pl.Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def gateway_env(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(bin_dir, "service-key", FAKE_SERVICE_KEY)
    _script(bin_dir, "register-service", FAKE_REGISTER)
    _script(bin_dir, "deregister-service", FAKE_DEREGISTER)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    monkeypatch.setenv("FAKE_KEYS", str(tmp_path / "keys.json"))
    monkeypatch.setenv("FAKE_REGISTER_LOG", str(tmp_path / "register.log"))
    monkeypatch.setenv("FAKE_PORT", "43210")
    return tmp_path


def test_register_returns_the_port_and_never_passes_public(gateway_env):
    port = asyncio.run(gateway.register_service("browser"))
    assert port == 43210
    assert (gateway_env / "register.log").read_text() == "browser\n"


def test_mint_list_revoke_round_trip(gateway_env):
    async def run():
        secret = await gateway.mint_key("browser", "browser-handover-abc", 1800)
        key_id = await gateway.find_key_id("browser", "browser-handover-abc")
        await gateway.revoke_key("browser", key_id)
        gone = await gateway.find_key_id("browser", "browser-handover-abc")
        return secret, key_id, gone

    secret, key_id, gone = asyncio.run(run())
    assert secret == "secret-browser-handover-abc" and key_id == "id1" and gone is None
    assert json.loads((gateway_env / "keys.json").read_text()) == []


def test_deregister_is_idempotent(gateway_env):
    asyncio.run(gateway.deregister_service("browser"))
    asyncio.run(gateway.deregister_service("browser"))
    assert (gateway_env / "register.log").read_text() == "deregister browser\nderegister browser\n"


def test_a_failing_script_raises_gateway_error(gateway_env, monkeypatch):
    _script(gateway_env / "bin", "register-service", f"#!{sys.executable}\nimport sys; print('vestad down', file=sys.stderr); sys.exit(1)\n")
    with pytest.raises(gateway.GatewayError, match="vestad down"):
        asyncio.run(gateway.register_service("browser"))


def test_missing_script_raises_gateway_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(gateway.GatewayError, match="register-service"):
        asyncio.run(gateway.register_service("browser"))
```

Add to `test_runtime_paths.py`: defaults `paths.novnc_dir == Path("/usr/share/novnc")`, `paths.x11_socket_dir == Path("/tmp/.X11-unix")`, `paths.handover_web == tmp_path / "agent/data/browser/handover-web"`, `paths.assets.name == "handover"`; overrides `VESTA_BROWSER_NOVNC_DIR`, `VESTA_BROWSER_X11_DIR`.

- [ ] **Step 2: Run, see failures** (module missing / attribute missing).

- [ ] **Step 3: Write `gateway.py` and extend `runtime_paths.py`**

```python
"""The vestad helpers as async calls: register and deregister the browser service, mint, find, and revoke its keys.

Each helper is the script the agent already has on PATH (`register-service`, `deregister-service`,
`service-key`); nothing here talks HTTP to vestad directly, so the gateway contract stays with
those scripts.
"""

from __future__ import annotations

import asyncio
import json

GATEWAY_TIMEOUT_SECS = 35


class GatewayError(Exception):
    """A vestad helper script failed or is missing; the message is its stderr or the missing name."""


async def _run(*argv: str) -> str:
    try:
        process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError as exc:
        raise GatewayError(f"{argv[0]} is not on PATH") from exc
    try:
        out, err = await asyncio.wait_for(process.communicate(), GATEWAY_TIMEOUT_SECS)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise GatewayError(f"{argv[0]} did not answer within {GATEWAY_TIMEOUT_SECS}s") from exc
    if process.returncode != 0:
        raise GatewayError(err.decode(errors="replace").strip() or f"{argv[0]} exited with {process.returncode}")
    return out.decode(errors="replace").strip()


async def register_service(name: str) -> int:
    port = await _run("register-service", name)
    if not port.isdigit():
        raise GatewayError(f"register-service answered without a port: {port!r}")
    return int(port)


async def deregister_service(name: str) -> None:
    await _run("deregister-service", name)


async def mint_key(service: str, label: str, ttl_secs: int) -> str:
    secret = await _run("service-key", "mint", service, "--label", label, "--ttl", str(ttl_secs))
    if not secret:
        raise GatewayError("service-key mint answered without a key")
    return secret


async def find_key_id(service: str, label: str) -> str | None:
    listing = json.loads(await _run("service-key", "list", service))
    if not isinstance(listing, dict) or not isinstance(listing["keys"], list):
        raise GatewayError("service-key list answered with an unexpected shape")
    for key in listing["keys"]:
        if isinstance(key, dict) and key["label"] == label:
            return str(key["id"])
    return None


async def revoke_key(service: str, key_id: str) -> None:
    await _run("service-key", "revoke", service, key_id)
```

`runtime_paths.py`: add the four fields with the env overrides (`novnc_dir=_override(env, "VESTA_BROWSER_NOVNC_DIR", pl.Path("/usr/share/novnc"))`, `x11_socket_dir=_override(env, "VESTA_BROWSER_X11_DIR", pl.Path("/tmp/.X11-unix"))`, `handover_web=root / "handover-web"`, `assets=SKILL_DIR / "cli/src/vesta_browser/assets/handover"`).

- [ ] **Step 4: Run tests, lint, commit** `feat(skills/browser): vestad gateway helpers for the handover route`.

---

### Task 2: Display stack and the noVNC page

**Files:**
- Create: `cli/src/vesta_browser/display.py`, `cli/src/vesta_browser/assets/handover/handover.html`
- Modify: `cli/tests/fakes.py` (fake `Xvfb`, `openbox`, `x11vnc`, `websockify`)
- Test: `cli/tests/test_display.py`

**Interfaces (display.py):**
- `@dataclass class DisplayStack(display: str, xvfb: Process, openbox: Process, x11vnc: Process, websockify: Process, vnc_port: int, web_port: int, webroot: Path)`.
- `def readiness(paths) -> dict[str, JsonValue]`: `{"ready": bool, "missing": [names]}` over `HANDOVER_BINARIES` (`shutil.which`) plus `"novnc"` when `paths.novnc_dir / "core/rfb.js"` is missing.
- `def display_reachable(paths, number: int) -> bool`: connect to the abstract socket `\0/tmp/.X11-unix/X<n>` OR the filesystem socket `paths.x11_socket_dir / f"X{n}"` (2 s timeout).
- `def own_display_serving(paths, number) -> bool`: filesystem socket only.
- `async def claim_display(paths) -> tuple[str, Process]`: first number in `[DISPLAY_FIRST, DISPLAY_LAST]` not reachable; spawn `Xvfb :<n> -screen 0 1280x800x24 -nolisten tcp` (own group, DEVNULL); poll `own_display_serving` every 0.2 s up to `XVFB_READY_TIMEOUT_SECS`; if the process exits, try the next number (up to 10 attempts); else raise `DisplayError`.
- `async def start_openbox(display) -> Process`: writes the rc XML from plan text to `<handover_web>/openbox-rc.xml`, runs `openbox --config-file <rc>` with `DISPLAY`.
- `def free_port(first: int) -> int`: bind `127.0.0.1` from `first` over 200 ports.
- `async def start_x11vnc(display, vnc_port) -> Process`: argv `x11vnc -display :N -localhost -rfbport <port> -forever -shared -nopw -quiet -threads -cursor most -cursorpos`, first plain then with `-noshm`; each attempt polls `port_serving(vnc_port)` up to `X11VNC_READY_TIMEOUT_SECS`, then sleeps `X11VNC_SETTLE_SECS` and requires the process still alive; a failed attempt is terminated before the next; both failing raise `DisplayError`.
- `def build_webroot(paths) -> Path`: recreate `paths.handover_web`, copy `handover.html`, `fonts/public-sans.woff2`, `macbook.png` from `paths.assets`, symlink `core` and `vendor` from `paths.novnc_dir`; raise `DisplayError` when `core/rfb.js` is missing.
- `async def start_websockify(webroot, web_port, vnc_port, log) -> Process`: argv `websockify --web <webroot> 0.0.0.0:<web_port> localhost:<vnc_port>`, stdout/stderr appended to `log`; poll `port_serving(web_port)` up to `WEB_READY_TIMEOUT_SECS`.
- `def port_serving(port) -> bool`: TCP connect to `127.0.0.1`.
- `async def stop_stack(stack) -> None`: kill_group websockify, x11vnc, openbox, then Xvfb last; unlink stale `/tmp/.X<n>-lock` and the socket under `paths.x11_socket_dir`.
- Env for every child: `DISPLAY=:<n>`, `PATH`, `HOME`, no `WAYLAND_DISPLAY`, `MOZ_ENABLE_WAYLAND=0`.

**The page:** extract `_PAGE_TEMPLATE` from `git show 2e689694:agent/skills/browser/cli/src/vesta_browser/handover.py` (lines 436-683) into a static `handover.html`. It must keep the relative websocket derivation (`location.pathname.replace(/[^/]*$/, '') + 'websockify'`), the relative `./core/...` imports, and the fonts/image paths; drop any Python substitution placeholders (inline the values or remove the feature). Vesta's brand voice applies to visible copy (no pronoun for Vesta, "agent" not "box").

**Fakes** (append to `fakes.py`, same `write_fakes`-style writer, new function `write_display_fakes(bin_dir, x11_dir) -> None`): `Xvfb` binds a unix socket at `<x11_dir>/X<n>` (parse `:N` from argv), writes its pid to `<x11_dir>/xvfb-<n>.pid`, and sleeps; `openbox` sleeps; `x11vnc` binds the `-rfbport` port on 127.0.0.1 and sleeps (a `FAKE_X11VNC_FAIL_SHM=1` env makes the first attempt without `-noshm` exit 1 immediately); `websockify` parses `--web <dir>` and `<host:port>`, serves the dir over HTTP on that port (python `http.server`) until killed.

- [ ] **Step 1: Failing tests** covering: `readiness` missing list (empty PATH → all four missing plus `novnc` when the dir lacks `core/rfb.js`); `claim_display` returns a display whose filesystem socket is reachable and skips a number that is already served (pre-bind a fake socket at `X99` and assert `:100`); `start_x11vnc` falls back to `-noshm` under `FAKE_X11VNC_FAIL_SHM=1` (assert the served port and that the surviving process argv contains `-noshm`, read via `/proc/<pid>/cmdline`); `build_webroot` copies the three files and symlinks `core`/`vendor`, and raises without `core/rfb.js`; `start_websockify` serves `GET /handover.html` (urllib) on the given port; `stop_stack` ends every pid (deadline polls) and leaves no socket file.

- [ ] **Step 2: Implement `display.py`, the fakes, and the page.** Keep `display.py` under 400 lines; one concern per function.

- [ ] **Step 3: Run tests, lint, guards; commit** `feat(skills/browser): display stack for handover (xvfb, openbox, x11vnc, websockify, novnc page)`.

---

### Task 3: Headed engine launches

**Files:**
- Modify: `cli/src/vesta_browser/runtimes.py` (`HeadedDisplay`), `chromium.py`, `camoufox.py`, `engines/camoufox/worker.py` (the `--headed` flag already exists; add `--window WxH`), `presets.py` (keep `fit_to_screen`)
- Test: `cli/tests/test_engines_headed.py`

**Interfaces:**
- `runtimes.HeadedDisplay(display: str, width: int, height: int)`.
- `chromium.start(session, paths, *, headed: HeadedDisplay | None = None)`: when headed, argv drops `--headless=new` and adds `--window-size=<w>,<h> --window-position=0,0` (keeps `--remote-debugging-port=0`, `--no-sandbox`); env adds `DISPLAY=<display>`. `launch_argv(paths, session, headed)` gains the parameter.
- `camoufox.start(session, paths, *, headed: HeadedDisplay | None = None)`: when headed, write `<profile>/user.js` with `user_pref("gfx.webrender.software", true);\nuser_pref("gfx.x11-glx.enabled", false);\n`, pass the preset through `presets.fit_to_screen(preset, w, h)` before writing the config, spawn the worker with `--headed` and env `DISPLAY=<display>`, `LIBGL_ALWAYS_SOFTWARE=1`, and no `MOZ_HEADLESS`. `camoufox.stop` (and `chromium.stop`) remove `<profile>/user.js` (`unlink(missing_ok=True)`) so a later headless launch does not inherit the prefs.
- The worker's `--headed` flag sets `headless=False` (already) and, new, when `--window WxH` is given passes `window=(w, h)` to `Camoufox(...)`.
- `handover.py` (Task 4) navigates the headed browser to the sign-in URL through the engine: after start, `await ENGINES[engine].exec_code(runtime, session, paths, f"new_tab({url!r})", 60)`; so no URL positional arg is needed on either engine.

- [ ] **Step 1: Failing tests:** `launch_argv(..., headed=HeadedDisplay(":101", 1280, 800))` has no `--headless=new`, has `--window-size=1280,800`; `chromium.start` with `headed` passes `DISPLAY=:101` to the process (extend the fake chromium to dump its env to `<profile>/env.json`); `camoufox.start` headed writes `user.js`, the config JSON has `screen.width == 1280`, the fake launch log records `headless == "False"` and `window == "(1280, 800)"`, the worker env has `DISPLAY`/`LIBGL_ALWAYS_SOFTWARE` (fake `Camoufox.__enter__` also dumps `os.environ` keys `DISPLAY` and `LIBGL_ALWAYS_SOFTWARE` into `launch.json`); `stop` removes `user.js` for both engines.

- [ ] **Step 2: Implement.** Do not change the headless path's behavior; the headless tests in `test_chromium.py`/`test_camoufox.py` must still pass unchanged.

- [ ] **Step 3: Run tests, lint, guards; commit** `feat(skills/browser): headed launches for chromium and camoufox`.

---

### Task 4: Handover orchestration and daemon ops

**Files:**
- Create: `cli/src/vesta_browser/handover.py`
- Modify: `daemon_state.py` (`handover: Handover | None = None`), `serve.py` (ops, `_stop_session` guard, shutdown)
- Test: `cli/tests/test_handover.py`

**Interfaces (handover.py):**
- `@dataclass class Handover(id: str, session: Session, stack: DisplayStack, key_id: str | None, key_label: str, user_url: str, expires_at: float (monotonic), expires_at_iso: str, state: HandoverState, task: asyncio.Task[None] | None)`, `HandoverState = Literal["starting","live","stopping","expired","failed","inactive"]`.
- `async def start(state, *, session_name, mode, url, minutes) -> Handover`: the flow below; any failure runs `stop(state, reason="failed")` and raises `BrowserError(handover_failed)`.
- `async def stop(state, *, reason: Literal["stopped","expired","failed"]) -> None`: idempotent.
- `async def status(state) -> dict[str, JsonValue]`.
- `async def op_handover_start|status|stop(state, request_id, request) -> Result`.
- `LIFETIME` validation: `minutes` absent → 30; must be `1..240` else `invalid_request`.

Flow of `start`:
1. Refuse when `state.handover` is not `None` and its state is `starting|live|stopping` → `handover_in_use`. Validate `minutes`, require `VESTAD_PUBLIC_URL` and `AGENT_NAME` in the environment (else `handover_failed` naming the missing variable), require `display.readiness(paths)["ready"]` (else `handover_failed` listing `missing`).
2. `session = resolve_session(table, session_name, mode)`; if `session.state in ("busy","starting")` → `invalid_request`; `await _stop_session(session)` (the headless runtime, if any); `mark(session, "handed_over")`; `handover_id = uuid4().hex[:8]`; `state.handover = Handover(state="starting", ...)`.
3. `web_port = await gateway.register_service("browser")` (private).
4. `display, xvfb = await display.claim_display(paths)`; `openbox`; `vnc_port = display.free_port(VNC_PORT_FIRST)`; `x11vnc`; `webroot = display.build_webroot(paths)`; `websockify` on `0.0.0.0:<web_port>` with the log `paths.log`.
5. Headed engine: `session.runtime = await ENGINES[session.engine].start(session, paths, headed=HeadedDisplay(display, 1280, 800))`; if `url`, `await ENGINES[...].exec_code(runtime, session, paths, f"new_tab({url!r})", 60)` and ignore a non-zero outcome except to add a warning.
6. `label = f"browser-handover-{handover_id}"`; `secret = await gateway.mint_key("browser", label, minutes * 60)`; `key_id = await gateway.find_key_id("browser", label)`; `user_url = f"{VESTAD_PUBLIC_URL.rstrip('/')}/agents/{AGENT_NAME}/browser/k/{secret}/handover.html"`. The secret is kept only inside `user_url`; never logged.
7. Health: `display.own_display_serving`, `port_serving(vnc_port)`, `port_serving(web_port)`, `runtime.process.returncode is None`; then `state = "live"` and spawn the expiry task (`asyncio.sleep(minutes * 60)` then `stop(state, reason="expired")`), owned in `state.tasks`.
8. Return `Handover`; the op answers `data = status payload` plus `session = info(session)`.

Flow of `stop(reason)`: set state `stopping`; cancel the expiry task (unless it is the caller); `gateway.revoke_key("browser", key_id)` when known (else `find_key_id` by label first); `gateway.deregister_service("browser")`; `_stop_session(session, force=True)` (stops the headed engine; `stop()` removes `user.js`); `display.stop_stack(stack)`; `shutil.rmtree(paths.handover_web, ignore_errors=True)`; each step in its own `try/except Exception` logged, so a failed revoke never skips the deregister; final state `reason` (`stopped` → `inactive` for status), session state `stopped` (a later exec restarts headless on the same profile). Gateway failures during stop add `cleanup_incomplete` to the op's warnings.

`status`: `{state, handover_id, session, engine, user_url, expires_at}`; when `state == "live"`, re-check the four health facts and report `failed` (and trigger `stop(reason="failed")` in a task) if any fails; `inactive` payload has nulls.

`serve.py`: register `"handover_start": handover.op_handover_start`, `"handover_status"`, `"handover_stop"`; `_stop_session` refuses `handed_over` unless `force`; `shutdown()` calls `await handover.stop(state, reason="stopped")` (bounded by the existing shutdown budget: run it inside `_stop_every_session`'s `asyncio.wait`) when a handover is `starting|live`; `_idle_sweep` skips `handed_over` (it does, via `idle_sessions` filtering `ready`).

- [ ] **Step 1: Failing tests** (via `serve.request`, with `write_fakes`, `write_display_fakes`, the gateway fakes on PATH, `VESTAD_PUBLIC_URL=https://gw.example`, `AGENT_NAME=luna`, and a fake noVNC dir):
  - start on a standard session: `ok`, `data.state == "live"`, `user_url == "https://gw.example/agents/luna/browser/k/secret-browser-handover-<id>/handover.html"`, `expires_at` about 30 min ahead, `sessions` shows `handed_over`, the register log has exactly `browser` (no `--public`), the fake chromium env dump has `DISPLAY`, and `GET <web_port>/handover.html` answers 200.
  - start on a stealth session with `--stealth` and `minutes=5`: `engine == "camoufox"`, the fake launch log shows `headless == "False"`, the key TTL recorded is 300.
  - exec against the handed-over session → `handover_in_use`; `session_stop` → `invalid_request`; a second `handover_start` → `handover_in_use`.
  - stop: key revoked (fake keys file empty), `deregister browser` logged, every display pid gone (deadline polls), session `stopped`, then an exec on the session succeeds headless again and `user.js` is gone.
  - expiry: `minutes=1` with `handover.MINUTE_SECS` patched to 0.5 → status becomes `expired` within 3 s, key revoked.
  - missing `VESTAD_PUBLIC_URL` → `handover_failed` naming it, nothing registered, session back to `stopped`.
  - a gateway mint failure (fake `service-key` exits 1) → `handover_failed`, the service is deregistered, the display pids are gone.
  - shutdown with a live handover: revoke and deregister logged, pids gone.

- [ ] **Step 2: Implement `handover.py`, the `State` field, the `serve.py` changes.** `handover.py` under 400 lines; the flow reads top to bottom in `start` with the health check as one function.

- [ ] **Step 3: Run the whole skill suite, lint, guards, contract row; commit** `feat(skills/browser): private handover through the daemon`.

---

### Task 5: Doctor, docs, and the PR

**Files:**
- Modify: `cli/src/vesta_browser/doctor.py` (a `handover` block: `display.readiness(paths)` plus `handover.status(state)`), `cli/tests/test_doctor.py`
- Modify: `AGENTS.md` (nothing to change if Task 13 of plan 1 already states handover ownership; verify), `agent/skills/browser/SKILL.md` interim banner (add one line: `browser handover start [--url <url>] [--session <name>] [--stealth]` returns `user_url` to send to the user; `browser handover stop` when they are done), under the `vesta-prompt-guide` skill.
- Modify: `docs/superpowers/specs/2026-09-04-browser-daemon-design.md` Handover section: websockify binds the port `register-service` returns; the page is a static asset under `cli/src/vesta_browser/assets/handover/`.

- [ ] **Step 1:** doctor test asserts `data["handover"]["ready"]` and `data["handover"]["state"] == "inactive"` with the fakes; implement.
- [ ] **Step 2:** docs edits; `./check.sh guards && ./check.sh agent`.
- [ ] **Step 3:** commit `feat(skills/browser): doctor reports handover readiness; docs`, push `feat/browser-handover`, open the PR against `feat/browser-daemon` titled `feat(skills/browser): private handover through the browser daemon`, body from the spec's Handover section, stating it stacks on #2391 and must release with PR 3.

---

## Self-review notes

- Spec coverage: handover flow steps 1 to 11 (Task 4), private registration and keyed URL (Tasks 1, 4), headed engines on the session profile (Task 3), status facts (Task 4), doctor (Task 5), `handed_over` protection (Task 4), no screenshot during handover (nothing captures), resume on the same profile (Task 4 stop + next exec).
- Divergences from the spec, deliberate: websockify binds vestad's allocated port (the spec assumed a free port); the page is a static asset (the spec assumed one existed); `viewer_connected` stays out of scope as the spec says.
- Interfaces consumed from plan 1: `_stop_session(session, force)`, `ENGINES`, `State`, `sessions.mark/info/resolve_session`, `kill_group`, `KILL_GRACE_SECS`, `p.error/result`, the CLI's existing `handover` argument mapping (`url`, `session`, `mode`, `minutes`).
