# Browser Daemon (PR 4: every session headed) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every browser session runs headed on its own Xvfb display, for both engines, from its first exec. There is no headless mode. A handover attaches the VNC stream to the session's live display and detaches it after, so the browser is never restarted around a handover. The `default` session is Vesta's one everyday profile.

**Why:** `--headless=new` announces `HeadlessChrome/<ver>` in the user agent, which sign-in flows and anti-bot layers reject outright, and Camoufox's own docs steer Linux users to Xvfb because headless Firefox is detectable. The browser-use CLI's normal flow is a headed, signed-in Chrome; this plan gives Vesta the same shape inside the container. Measured on the live run of 2026-09-05: the handover restarted the browser twice (headless to headed and back), which is what made a profile accumulate tabs and lose page state.

**Architecture:** `display.py` grows a per-session display (`SessionDisplay`: Xvfb plus openbox) and shrinks the handover's stack to the stream alone (`StreamStack`: x11vnc plus websockify). `session_control.py` claims the display before the engine starts and releases it after the engine stops, and hands the engine a `HeadedDisplay` every time. Both engines drop their headless branch. `handover.py` reads the session's display instead of building one and returns the session to `ready` instead of `stopped`. Readiness splits into the display (needed by every exec) and the stream (needed by a handover).

**Tech Stack:** as plans 1 to 3. Xvfb and openbox join Chromium and Camoufox as engine prerequisites; `install-engines.sh` installs them.

**Spec:** `docs/superpowers/specs/2026-09-04-browser-daemon-design.md`, decision 17 and the amended Architecture, Sessions and engines, Handover, Packaging, and Testing sections.

**Base:** branch `feat/browser-headed`, stacked on `feat/browser-callers` (PR #2396). Worktree `/home/emi/vesta-wt-browser-spec`. PR 4 of the stack; the four release together.

## Global Constraints

- Everything in plans 1 to 3's Global Constraints still binds: Python conventions (no `getattr`/`.get()`/`hasattr`, no `Any`/`object`, no lint escapes, comments capped at 8 lines, one JSON line per command), async rules (no blocking calls in coroutines, own every task, cleanup then re-raise on cancel), ASD-STE100 prose with no spaced dashes, "Vesta" never gets a pronoun, nothing under `agent/` describes a previous design (state the mechanism, never what changed). Commit trailers: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01VWMfwWdkJHjAXDbAJjv5Kd`.
- **No live testing on this host.** Every test runs against the fakes in `cli/tests/fakes.py`. Never launch a real Xvfb, browser, or vestad script, never scan `/proc` for or signal processes you did not start in the test's own tmp dir. The live run is the user's, after the PR.
- Screen geometry stays `SCREEN_W, SCREEN_H = 1280, 800` for every session and engine (a real 13" laptop size; the handover page frames exactly that). Camoufox presets are always refit with `fit_to_screen`.
- Session states are unchanged: `starting | ready | busy | handed_over | stopped`. A handover ends with the session `ready` (browser and tabs intact) when its runtime is alive, `stopped` otherwise, and the session is touched so the idle sweep cannot stop it in the seconds before the caller's next exec.
- The display is owned by `session_control.py` alone: `ensure_running` claims it before the engine starts and releases it if the engine fails to start; `stop_session` releases it after the engine stops (in a `finally`, so a failing engine stop never leaks an Xvfb). Engines receive a `HeadedDisplay` and never touch `display.py`.
- Shutdown budgets are unchanged (`SHUTDOWN_BUDGET_SECS`, `HANDOVER_SHUTDOWN_SECS`, `MIN_SESSION_BUDGET_SECS`). `_stop_every_session`'s SIGKILL escalation must cover a stuck session's Xvfb and openbox as well as its engine.
- Test commands: `cd agent && uv run --project skills/browser/cli pytest skills/browser/cli/tests -q`, `uv run ruff check skills/browser && uv run ruff format --check skills/browser`, `./check.sh guards` from the repo root, `uv run --project skills/microsoft/cli pytest skills/microsoft/cli/tests -q` for Task 5, and `uv run pytest tests/test_daemon_contract.py -k browser` for the contract row.

---

## File structure

```
agent/skills/browser/
  install-engines.sh                       Task 1: also installs xvfb, openbox, x11vnc, novnc when missing
  cli/src/vesta_browser/
    display.py                             Task 1: SessionDisplay start/stop, StreamStack, readiness split, DISPLAY_APT_LINE
    runtimes.py                            Task 2: HeadedDisplay docstring (the display every engine launches onto)
    chromium.py                            Task 2: headed-only launch_argv/start, DISPLAY always in the browser env
    camoufox.py                            Task 2: headed-only start/worker_argv, user.js written at every start
    sessions.py                            Task 3: Session.display
    session_control.py                     Task 3: claims and releases the display around the engine
    daemon_state.py                        Task 3: routes() reports display readiness
    doctor.py                              Task 3: engines.display block; handover block reads stream readiness
    serve.py                               Task 3: shutdown escalation covers display processes
    handover.py                            Task 4: attaches the stream to the session's display; session ends ready
    handover_state.py                      Task 4: Handover.stack: StreamStack | None
  engines/camoufox/worker.py               Task 2: always headed, --window required, no --headed flag
  SKILL.md, SETUP.md                       Task 5
agent/skills/microsoft/cli/src/microsoft_cli/capture.py   Task 5: finish_interactive comment and test names
agent/core/migrations/2026-09-browser-daemon.md           Task 5: step 1 and step 6 wording
cli/tests/
  fakes.py                                 Task 3: FAKE_CHROMIUM keeps recording env.json (already does)
  test_display.py                          Task 1
  test_chromium.py, test_camoufox.py, test_worker.py   Task 2 (absorb test_engines_headed.py, which is deleted)
  test_serve_exec.py, test_sessions.py, test_doctor.py Task 3
  test_handover.py                         Task 4
```

---

### Task 1: The session display and the stream stack (`display.py`, `install-engines.sh`)

**Files:**
- Modify: `cli/src/vesta_browser/display.py`, `install-engines.sh`
- Test: `cli/tests/test_display.py`

**Interfaces:**
- `DISPLAY_BINARIES = ("Xvfb", "openbox")`, `STREAM_BINARIES = ("x11vnc", "websockify")`, `DISPLAY_APT_LINE = "apt-get install -y xvfb openbox x11vnc novnc"` (replaces `HANDOVER_BINARIES` and `HANDOVER_APT_LINE`).
- `missing_display_binaries(paths) -> list[str]`, `missing_stream_binaries(paths) -> list[str]` (the stream list adds `novnc` when `core/rfb.js` is absent). `readiness(paths)` is replaced by `display_readiness(paths)` and `stream_readiness(paths)`, each `{"ready": bool, "missing": [...]}`.
- `@dataclass class SessionDisplay: display: str; xvfb: Process; openbox: Process`.
- `async def start_session_display(paths) -> SessionDisplay`: `claim_display`, then `start_openbox`; if openbox cannot be spawned (`OSError`), kill the Xvfb group and raise `DisplayError`.
- `async def stop_session_display(paths, session_display) -> None`: kill openbox, then Xvfb, then `_clear_stale_records`.
- `@dataclass class StreamStack: x11vnc: Process; websockify: Process; vnc_port: int; web_port: int; webroot: pl.Path` (replaces `DisplayStack`; no display, no xvfb, no openbox).
- `async def stop_stack(stack: StreamStack) -> None`: kill websockify and x11vnc together. No records to clear.
- Module docstring: the display is now every session's, not the handover's; the two-socket claim reasoning stays.
- `install-engines.sh`: after the chromium block, install `xvfb openbox x11vnc novnc` when any of `Xvfb`, `openbox`, `x11vnc`, `websockify` is missing from PATH or `/usr/share/novnc/core/rfb.js` is absent (one apt call, same `--no-install-recommends` and list cleanup as the chromium block). Header comment names the display packages.

- [ ] **Step 1: Failing tests** in `test_display.py`: `start_session_display` returns a display this container serves with two recorded pids (Xvfb and openbox); `stop_session_display` ends both and removes the socket file; `stop_stack` ends x11vnc and websockify and leaves Xvfb and openbox alive; `display_readiness` lists a missing `Xvfb`/`openbox`, `stream_readiness` lists a missing `x11vnc`/`websockify`/`novnc`; both ready with the fakes and a novnc dir. Rewrite `test_readiness_*` and `test_stop_stack_*` to the new names.
- [ ] **Step 2: Implement** as specified. Update every in-module reference (`build_webroot` error text uses `DISPLAY_APT_LINE`).
- [ ] **Step 3:** suite, ruff, shellcheck (`./check.sh guards` covers `install-engines.sh`). Commit: `feat(skills/browser): sessions own an X display; the handover stack is the stream alone`.

---

### Task 2: Both engines launch headed, always

**Files:**
- Modify: `cli/src/vesta_browser/runtimes.py`, `chromium.py`, `camoufox.py`, `engines/camoufox/worker.py`
- Test: `cli/tests/test_chromium.py`, `test_camoufox.py`, `test_worker.py`; delete `cli/tests/test_engines_headed.py` after moving its headed cases.

**Interfaces:**
- `HeadedDisplay` docstring: "The X display and window size every engine launches onto: a session's own Xvfb."
- `chromium.launch_argv(paths, session, headed: HeadedDisplay) -> list[str]`: `--window-size={w},{h}`, `--window-position=0,0`, never `--headless=new`; the rest unchanged. `_browser_env(headed)` always sets `DISPLAY`. `start(session, paths, *, headed: HeadedDisplay)`; `pin_startup_pref` stays.
- `camoufox.worker_argv(paths, session, config_path, headed: HeadedDisplay)`: always `--window {w}x{h}`, no `--headed`. `start(session, paths, *, headed: HeadedDisplay)`: always `fit_to_screen`, always writes `user.js` (software WebRender prefs), env always `DISPLAY` and `LIBGL_ALWAYS_SOFTWARE=1`. `stop` no longer unlinks `user.js` (there is no headless launch it could leak into; delete that comment).
- `worker.py`: drop `--headed`; `--window` becomes `required=True`; `"headless": False`. Comment in `main` stays about `ff_version`/addons.
- `child_env` for browser-use is unchanged (`DISPLAY` stays absent from the exec child: the harness talks CDP and never opens the display).

- [ ] **Step 1: Failing tests.** `test_chromium`: `test_launch_argv_is_headed_sandboxless_and_profile_scoped` (window flags present, `--headless=new` absent); every `chromium.start(...)` call passes `headed=HEADED`; `test_start_passes_the_display_to_the_browser_process` (moved). `test_camoufox`: `worker_argv` carries `--window 1280x800` and no `--headed`; `start` writes `user.js` and the refit config, env carries `DISPLAY` and `LIBGL_ALWAYS_SOFTWARE` (moved from `test_engines_headed`); `stop` leaves `user.js` in place. `test_worker`: the fixture passes `--window 1280x800`; launch options assert `headless == "False"` and `window == "(1280, 800)"`.
- [ ] **Step 2: Implement.** Delete `test_engines_headed.py`.
- [ ] **Step 3:** suite, ruff. Commit: `feat(skills/browser): both engines launch headed on the session's display`.

---

### Task 3: The session owns its display; readiness and shutdown follow

**Files:**
- Modify: `cli/src/vesta_browser/sessions.py`, `session_control.py`, `daemon_state.py`, `doctor.py`, `serve.py`
- Test: `cli/tests/test_serve_exec.py`, `test_sessions.py`, `test_doctor.py`, `fakes.py` as needed

**Interfaces:**
- `Session.display: display.SessionDisplay | None = None` (import the type from `display.py`; `sessions.py` sits below it in the graph already through `runtimes.py`; if a cycle appears, move `SessionDisplay` into `runtimes.py` and have `display.py` import it from there).
- `session_control.ensure_running`: `mark starting`; `session.display = await display.start_session_display(state.paths)`; build `HeadedDisplay(session.display.display, display.SCREEN_W, display.SCREEN_H)`; `session.runtime = await ENGINES[engine].start(session, paths, headed=headed)`; on any exception: stop the display if it was started, clear both fields, `mark stopped`, re-raise. Cancellation follows the same cleanup path then re-raises.
- `session_control.stop_session`: after clearing `runtime`, also take `session.display` into a local and clear it; `try: engine stop finally: stop_session_display`.
- `serve._stop_every_session`: `stuck` covers both the runtime process and the display's two processes of each pending session (collect them before the stops start, as today for runtimes).
- `daemon_state.routes(paths)`: each route's `ready` is `engine binaries present and display ready`; add top-level `"display": display_readiness(paths)`. `doctor.report`: `"handover": {**display.stream_readiness(paths), **diagnostic(...)}`.
- `serve.py` comment block at lines 36 to 42 rewritten for the new shape (the handover shutdown kills the stream; sessions kill their own displays inside the session budget).

- [ ] **Step 1: Failing tests.** `test_serve_exec`: the `paths` fixture writes the display fakes into a short `/tmp` X11 dir (as `test_handover.rig` does: `tempfile.mkdtemp(dir="/tmp")`, `VESTA_BROWSER_X11_DIR`, cleaned up after) and exposes the pids file; new tests: an exec starts Xvfb and openbox and the fake chromium's `env.json` carries that `DISPLAY`; `session stop` ends the display pids; the idle sweep ends them; `test_shutdown_kills_a_session_whose_engine_stop_hangs` also asserts the display pids are dead; an engine start failure (`test_a_total_start_failure_*`) leaves no display pid alive and `session.display is None`. `test_doctor`: `engines.display.ready` and `engines.routes.*.ready` false when `Xvfb` is missing from PATH, true with the fakes; the `handover` block lists stream binaries only. `test_sessions`: `Session.display` defaults to `None`.
- [ ] **Step 2: Implement.**
- [ ] **Step 3:** suite, ruff, `./check.sh guards` (import-cycle guard), contract row. Commit: `feat(skills/browser): the session owns its display from first exec to stop`.

---

### Task 4: The handover attaches to the live display

**Files:**
- Modify: `cli/src/vesta_browser/handover.py`, `handover_state.py`
- Test: `cli/tests/test_handover.py`

**Interfaces:**
- `Handover.stack: StreamStack | None`.
- `handover.start`: resolve the session; refuse `busy`/`starting` as today; `await ensure_running(state, session)` (an `engine_unavailable` propagates unchanged, before anything is marked); then `mark handed_over` and run the bring-up as today.
- `_bring_up`: `register_service` → `build_webroot` → `start_x11vnc(session.display.display, vnc_port)` → `start_websockify` → `handover.stack = StreamStack(...)` → navigate (the activating program from PR 3) → mint → health → `live`. `_start_display` becomes `_start_stream(paths, display_name, web_port) -> StreamStack` with the same tear-back-down-on-failure shape (two processes).
- `_healthy`: `session.display is not None and session.runtime is not None and own_display_serving(session.display number) and both ports serving and runtime process alive`.
- `_teardown(state, handover, reason, gateway_timeout)`: cancel task, release key, deregister, `_tear_stream`, remove webroot. No session stop (drop `stop_session_too`). Then: `sessions_mod.mark(session, "ready" if session.runtime is not None and session.runtime.process.returncode is None else "stopped")`, `sessions_mod.touch(state.table, session)`.
- `shutdown`: unchanged in shape, `_tear_stream` in place of `_tear_display`; the docstring's "browser is left whole for the session teardown" still holds.
- Module docstring and `serve.shutdown` docstring: the handover owns the stream, the session owns the browser and the display.
- Remove the now-unused `HeadedDisplay` import and the `ENGINES` import if nothing else uses it in `handover.py` (the navigate step still uses `ENGINES[...].exec_code`).

- [ ] **Step 1: Failing tests** in `test_handover.py`: (a) an exec first, then `handover_start`, then `handover_stop`: the display pids from the exec (Xvfb, openbox) stay alive across the whole cycle, the two stream pids die on stop, the session reads `ready` after stop, and an exec right after answers with no `worker_restarted` warning; (b) a handover on a cold session starts the display and the browser itself and `sessions` lists it `handed_over`; (c) the stealth cycle likewise (fake camoufox launch options show `headless == "False"`); (d) `test_handover_stop_releases_the_key_the_service_and_the_display` becomes `..._and_the_stream` (Xvfb alive, x11vnc and websockify dead); (e) `test_daemon_shutdown_stops_a_live_handover` and `test_a_shutdown_during_start_leaves_no_display_behind` assert every display and stream pid dead after shutdown (the session teardown kills the display); (f) an engine start failure on `handover_start` answers `engine_unavailable`, registers nothing, and leaves the session `stopped` with no pids alive. Keep every existing assertion that still holds (key TTL, `/k/` URL, `handover_in_use`, doctor secret, expiry, mint rollback, lifetime range, budget).
- [ ] **Step 2: Implement.**
- [ ] **Step 3:** suite, ruff, guards. Commit: `feat(skills/browser): handover streams the session's live display and leaves the browser running`.

---

### Task 5: Docs, callers, migration

**Files:**
- Modify: `agent/skills/browser/SKILL.md`, `SETUP.md`, `agent/skills/microsoft/cli/src/microsoft_cli/capture.py`, `agent/skills/microsoft/cli/tests/test_capture.py`, `agent/core/migrations/2026-09-browser-daemon.md`

**Content (state the mechanism, never the change):**
- `SKILL.md` sessions paragraph: "`--session` defaults to `default`, Vesta's one everyday browser: sign in there the way a person signs in to their own Chrome, and it stays signed in. Use a named session only to isolate an account (a second Microsoft tenant) or a parallel task." Keep the naming rule and the idle-stop sentence. Handover section: "The browser keeps running through the handover; when it ends the session is `ready` with its tabs and sign-in in place, so continue with `browser exec` on the same session name." Remove any sentence implying a restart. Recovery: `browser doctor` reports display readiness.
- `SETUP.md`: the display packages (`Xvfb`, `openbox`) are required by every program, and `x11vnc`, `websockify`, `/usr/share/novnc` by a handover; `install-engines.sh` installs all of them; `browser doctor` shows `engines.display` and `handover`.
- `capture.py` `finish_interactive`: comment becomes "The stop detaches the user's view; the session keeps running signed in, so the harvest reads it directly." `stop()` docstring unchanged in meaning. Test names: `test_refresh_harvests_headlessly` → `test_refresh_harvests_without_a_handover`; the `# no handover, no window` comment stays true.
- Migration step 1: "Installs Chromium, the display packages (Xvfb, openbox, x11vnc, noVNC), and the pinned Camoufox bundle when missing". Step 6: "`browser doctor`; both engine routes and `engines.display` must read `ready: true`".
- Grep `agent/skills/browser` and `agent/skills/microsoft` for `headless` and resolve every hit that describes the daemon (a recipe describing a site's behavior stays).

- [ ] **Step 1:** edit; run `uv run --project skills/microsoft/cli pytest skills/microsoft/cli/tests -q`, `./check.sh guards` (dash and convention guards on SKILL.md).
- [ ] **Step 2:** Commit: `docs(skills/browser): every session runs headed; the default session is the everyday profile`.

---

## Whole-branch review

After Task 5: one reviewer reads the full `feat/browser-callers..feat/browser-headed` diff against the spec's decision 17 and this plan, with the AGENTS.md conventions; fix rounds until clean. Then push and open PR 4 against `feat/browser-callers` with the body naming the live checks it owes (a real headed exec on Debian chromium and on Camoufox, a handover cycle asserting the browser pid survives, Microsoft sign-in and refresh on a real tenant).
