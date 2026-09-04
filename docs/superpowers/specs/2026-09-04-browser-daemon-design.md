# Browser daemon: one owner for every browser action

**Date:** 2026-09-04
**Status:** Design, approved for planning. No code written.
**Supersedes:** the review report "Hermes Browser Runtime with a Vesta Skill and Browser Daemon" (2026-09-04, not committed). Every claim in that report was checked against the repo at `f909df0d` and the upstream revisions listed under Sources. The corrections are recorded in Ground truth.

## Goal

Vesta browses the web through one skill, one command, and one daemon. Vesta writes a complete browser program in Python, pipes it to `browser exec`, and reads one structured result. A per-agent browser daemon owns every browser decision: validation, engine selection, sessions, browser processes, execution children, artifacts, timeouts, cleanup, diagnostics, and handover. Two engines sit behind it: Chromium through the pinned Browser Use CLI and Browser Harness over CDP (the default), and Camoufox through Playwright Firefox (stealth, on explicit request). The skill interface stays what every Vesta capability is: `SKILL.md`, `SETUP.md`, and a CLI reached through Bash. No native tool is added to the agent core.

Names: "Vesta" is the live agent in the container. The harness is `agent/core/`. The report's "Claude" means Vesta throughout.

## Ground truth

Verified in the tree at `f909df0d` and in the upstream sources.

### Today's browser skill (`agent/skills/browser/`)

- **Camoufox is the only engine that launches.** `cli.py` → `admin.launch_browser` → `launcher.launch`. `cdp_backend.py` is a BiDi-to-CDP translator that attaches to a Chrome the user exposed; it launches nothing. Chromium is not in the image.
- **Camoufox is downloaded at first use**, pinned (`CAMOUFOX_RELEASE_TAG = "v150.0.2-beta.25"`, per-arch sha256 in `launcher.py:35-38`), into `~/.cache/camoufox/<tag>/`. `launcher.py` also repairs Camoufox's `omni.ja` search stub (`LEGACY(remove-when: CAMOUFOX_RELEASE_TAG moves past v150.0.2-beta.25)`, `launcher.py:211`).
- **One implicit daemon per session name**, socket `/tmp/vesta-browser-<name>.sock` (0600), pid and log in `/tmp`. Every command calls `admin.ensure_daemon()`. There is no `browser daemon` verb, no row in `agent/tests/test_daemon_contract.py`, and no record under `~/agent/data/daemons/`. The skill is outside the daemon contract.
- **31 subcommands** (`launch connect mode doctor stop stop-all sessions prune handover open navigate reload back forward snapshot screenshot pdf click type press hover scroll wait evaluate|js bidi http-get fetch tabs focus close resize`) plus a no-argv stdin mode that `exec`s Python with the helpers injected (`cli.py:440-453`). `browser bidi` exposes raw WebDriver BiDi.
- **Semantic refs** are `[ref=e12]` in the snapshot text and bare `e5` on the command line, resolved in the page realm by `vendor/walker.js`. `@e12` is accepted but never documented.
- **Handover** shells Xvfb → openbox → x11vnc → websockify plus noVNC assets, then a headed Camoufox on the shared `default` profile. It calls `register-service browser --public` (`handover.py:177-183`) and returns `user_url = $VESTAD_PUBLIC_URL/agents/$AGENT_NAME/browser/handover.html`. `agent/tests/test_service_exposure.py:25` and `AGENTS.md` pin it as one of four allowed public services. No service key is used anywhere in the skill.
- **Dependencies**: `websockets>=15` alone. No Browser Use, Browser Harness, or Playwright. `interaction-skills/profile-sync.md` documents functions that do not exist in this codebase.
- 3876 lines across 11 modules, 2854 lines of tests in `cli/tests`.

### Callers outside the skill

- **Maps** (`agent/skills/maps/cli/src/gmaps_cli/browser_bridge.py`): `browser open <url>` and `browser evaluate <js>` on the default session, with `DISPLAY=:99` forced into the child env. It parses stdout as the JSON-encoded JS return value and treats a non-zero exit as `BrowserUnavailableError`. It never manages sessions, daemons, or handover. `maps/SKILL.md:130-134` teaches `browser handover start --url <google sign-in>` and `browser handover stop`.
- **Microsoft** (`microsoft_cli/capture.py`): `stop-all`, `handover start --url <url> --user-data-dir ~/.microsoft/browser-profiles/<email>`, `handover stop`, `open`, `evaluate`, `snapshot` (as a liveness probe), all with `BROWSER_SESSION=handover` and `DISPLAY` stripped. It parses `handover start` for `user_url`. `monitor.py:561-577` runs `capture.refresh_and_save` unattended, so the microsoft daemon starts a headed handover with no user present to refresh tokens. A second call site, `auth_commands.py:270-284` and `:429-441`, shells `browser launch --stealth`, `open`, `evaluate` on the default session with `DISPLAY=:99`.
- **Flights** (`flights/SKILL.md:73-76`) teaches `browser launch` and prose steps. **`agent/MEMORY.md:27`** names `browser handover start`. **`vestad/SKILL.md:79`** uses `deregister-service browser` as its example. **`register-service:4`** lists "a browser handover" as a legitimate `--public` case.
- `writing/gptzero.py` runs its own Xvfb and drives a Chromium over CDP port 9222. It never touches the `browser` CLI. Out of scope here.
- `browser` is in `agent/core/default-skills.txt` (third entry), as are `maps` and `microsoft`.

### Repo conventions the design must obey

- **Daemon contract** (`agent/skills/vestad/SKILL.md:98-206`, `agent/tests/test_daemon_contract.py`): `<skill> daemon start|stop|restart|status`, one JSON line per verb, pid record `~/agent/data/daemons/<name>.pid` as `<pid> <starttime>`, log `~/agent/logs/<name>.log`, `DAEMON_READY_TIMEOUT_SECS` and `DAEMON_STOP_TIMEOUT_SECS` defined per launcher, exclusive-create pid claim, ready-before-return, fail closed, SIGTERM then SIGKILL, status is a local read. A daemon that serves no port reports `"port": null` and sits in the table as `serves_port=False`. Skill state lives in `~/agent/data/<skill>/`, never in `daemons/` (`SKILL.md:265`). Boot empties `daemons/`.
- **Restart skill**: `~/agent/skills/restart/daemons.sh` holds one bare `<skill> daemon start` per line; a skill's `SETUP.md` tells Vesta to add the line.
- **Skill CLIs are installed at activation**, by `SETUP.md` (`uv tool install --editable ~/agent/skills/<skill>/cli`), never by the Dockerfile. The Dockerfile has no `uv tool install`.
- **Fleet upgrades never rerun the Dockerfile** (`vestad/src/docker.rs:217-219`): a rebuild recreates the writable layer from a snapshot. System packages a skill needs go into a commented `apt-get` layer for fresh images and into a prompt migration for the fleet, exactly as `agent/core/migrations/2026-07-handover-deps.md` did for Xvfb.
- **Private services and keys**: `register-service <name>` (no `--public`) registers private; `service-key mint <service> [--label] [--ttl <secs>]` prints the secret once; `service-key list <service>`, `service-key revoke <service> <id>`. The path form is `$VESTAD_PUBLIC_URL/agents/$AGENT_NAME/<service>/k/<key>/...`; vestad strips the prefix only when the key opens that service (`agent_proxy.rs:138-150`). Default TTL is 30 days (`service_keys.rs:16`).
- **Output contract**: stdout carries the successful result, failures print on stderr and exit non-zero, JSON envelopes print as one line (`scripts/check-conventions.py`).
- The Bash tool Vesta runs commands through has a default timeout of 120 s and a maximum of 600 s per call.

### Upstream facts

- **Hermes** `tools/browser_use_cli.py` @ `6327930`: native tool `browser_exec`, Python on stdin to `browser-use` or `uvx browser-use`, timeout clamped 5 to 1800 s, `_URL_RE` literal scan, `PYTHONPATH`/`PYTHONHOME` stripped, stderr capped at 4000 chars (stdout uncapped), screenshots found by scanning stdout for image paths newer than exec start, `_OWN_TAB_PREAMBLE` for named sessions, backend order: `BU_CDP_WS`/`BU_CDP_URL` env, configured CDP URL, cloud provider, Lightpanda engine, local Chrome. `browser_registry.py` registers nothing itself; plugins register Browser Use Cloud, Browserbase, Firecrawl. Lightpanda is an engine, not a provider.
- **Browser Use** @ `fe5ad35`: `version = "0.13.10"`, `browser-harness==0.1.13`, MIT, no Playwright. `browser_use/cli.py` is "Browser Use CLI backed by Browser Harness": it executes Python piped on stdin; `--session` and `--cdp-url` are rejected in favor of `BU_NAME` and `BU_CDP_URL` env vars; subcommands `install`, `init`, `skill`, `--mcp`, `--doctor`, `--reload`. `browser/session.py` is built on `cdp_use`; no Firefox, BiDi, or WebDriver.
- **Browser Harness** @ `10b2086`: MIT. `daemon.py`: "CDP WS holder + IPC relay (Unix socket on POSIX). One daemon per BU_NAME." It connects to a running browser (`BU_CDP_URL`, `DevToolsActivePort`, or `/json/version` probe); it launches no browser. Named daemons create their own background tab. `run.py` reads code from stdin and `exec`s it in a fresh interpreter per call. `helpers.py` defines `cdp, drain_events, goto_url, page_info, click_at_xy, type_text, fill_input, press_key, scroll, capture_screenshot, list_tabs, current_tab, activate_tab, switch_tab, new_tab, close_tab, ensure_real_tab, iframe_target, wait, wait_for_load, wait_for_element, wait_for_network_idle, js, dispatch_key, upload_file, http_get`. `capture_screenshot` writes `shot.png` under its temp dir and returns the path.
- **Camoufox**: Playwright Firefox, `playwright<1.63`, Python lib MIT, browser MPL 2.0, no CDP. The remote server page says "This feature is experimental. It uses a hacky workaround to gain access to undocumented Playwright methods."

## Decisions (locked)

1. **Ordinary skill, no native tool.** Vesta reaches the browser through `SKILL.md` and Bash. Nothing browser-specific enters `agent/core/tools.py`, `client.py`, or `cc_sdk/`. Rejected: Hermes' native `browser_exec` (a second invocation path, and the internal callers would bypass it).
2. **One daemon per agent owns every browser decision.** The CLI is a stdlib RPC client; the internal callers use the same CLI. Rejected: keeping today's per-session implicit daemons (outside the daemon contract, `/tmp` state, no lifecycle verbs).
3. **Two engines, one policy layer.** Chromium through the pinned `browser-use` CLI and Browser Harness over CDP. Camoufox through a daemon-supervised worker using the official Camoufox Playwright API. Camoufox has no CDP, so it cannot be another Browser Harness endpoint. Rejected: a CDP-to-Firefox translator (today's `cdp_backend.py` shows the cost), a fork of Browser Use.
4. **`browser-use` CLI is the Chromium executor** (user decision). It pins `browser-harness==0.1.13` and keeps the cloud and recordings paths reachable later. Rejected for now: depending on `browser-harness` alone (lighter, same helpers; revisit if the browser-use dependency set causes trouble).
5. **Standard by default, `--stealth` on explicit request.** `standard → chromium`, `stealth → camoufox`. The daemon reports the resolved engine in every result. No automatic replay of a failed standard request in stealth: a browser action may have submitted a form or a payment.
6. **A session is pinned to its engine for life.** An omitted mode inherits; an explicit conflicting mode fails `session_engine_conflict`. Switching engines means a new session name. Cookies, tabs, and profiles never cross engines.
7. **One browser process and one profile per session.** Sessions are isolated by construction (Microsoft's per-account profiles need this). Idle sessions stop their browser after `SESSION_IDLE_STOP_SECS`; the profile persists; the next call restarts it. Rejected: one shared Chromium with own-tab protection (shares logins across sessions; today's shared `default` profile is why Microsoft needed `--user-data-dir`).
8. **No workspace ids.** Artifacts land in `~/agent/data/browser/artifacts/<session>/` and are pruned by age. Rejected: opaque daemon-issued `w_...` ids (bookkeeping Vesta has to carry between calls, for no consumer that needs it).
9. **Slim envelope.** `ok`, `error`, `session`, `page`, `output`, `artifacts`, `warnings`. Rejected: per-helper action markers and `visual: current|stale|absent` (they require wrapping every upstream helper, and `observed_at` plus `captured_at` let Vesta compare the two timestamps itself).
10. **The daemon mints and revokes the handover key.** `browser handover start` returns a ready `user_url`; stop, expiry, failure, or daemon shutdown revokes the key and deregisters the service. Rejected: Vesta running `service-key mint/list/revoke` around every handover (three extra steps and a key it can forget).
11. **Handover is private.** `register-service browser` with no `--public`, path-keyed URL. Removes one of the four allowed public services.
12. **No literal URL scan, no network policy in the daemon.** Vesta already holds unrestricted Bash; a regex over literals in model-written Python guards nothing and costs a false sense of a sandbox. The daemon still builds a minimal child environment and strips `PYTHONPATH`, `PYTHONHOME`, and unrelated secrets, because that is hygiene, not security theater. Rejected: Hermes' `_URL_RE` scan.
13. **Timeouts fit the Bash tool.** Default `EXEC_TIMEOUT_DEFAULT_SECS = 120`, range 5 to `EXEC_TIMEOUT_MAX_SECS = 600`. Rejected: Hermes' 1800 s ceiling (the Bash tool cannot wait that long).
14. **Browsers are system packages; venvs install at activation.** `install-engines.sh` installs Chromium from apt and the pinned, sha256-checked Camoufox build. The Dockerfile runs it for fresh images; a prompt migration runs it on the fleet. The three Python projects (`cli/`, `engines/chromium/`, `engines/camoufox/`) install from `SETUP.md` like every other skill. Rejected: venvs baked into the image (against convention, and unreachable by the fleet anyway).
15. **Replace in one release, no rollback switch.** The old runtime is deleted in the same release the daemon lands. The beta channel and the pre-update snapshot are the rollback. Rejected: a `LEGACY` dual path for one release window.
16. **Callers move to `browser exec` in the same release.** Maps and Microsoft are rewritten; no compatibility translations of `open`, `evaluate`, `snapshot`, `launch`. Microsoft's second call site folds into `capture.py`.

## Architecture

```text
User message, notification, or scheduled work
                    |
                    v
          harness turn (agent/core)
                    |
                    v
        Vesta loads SKILL.md, writes Python
                    |
                    v
   Bash: browser exec --session <name> [--stealth] <<'PY' ... PY
                    |
                    v
        thin CLI (stdlib)  ── one JSON request ──▶  ~/agent/data/browser/browser.sock (0600)
                                                          |
                                                          v
                                        browser daemon (`browser serve`)
                                        validation · session table · engine routing
                                        process supervision · artifacts · timeouts
                                        page observation · doctor · handover
                                            |                          |
                              standard ─────┘                          └───── stealth
                                 |                                              |
                                 v                                              v
                 per-session Chromium (headless, loopback CDP)     per-session Camoufox worker
                 browser-use CLI child per exec                    (one process: sync Camoufox +
                 BU_NAME=<session> BU_CDP_URL=<loopback>           Playwright Firefox + helpers)
                 Browser Harness daemon per BU_NAME                fresh globals per exec
```

Vesta is the planner. The daemon never chooses a goal; it executes and supervises programs Vesta or an internal caller submits.

## Layout and paths

```
agent/skills/browser/
  SKILL.md                     model-facing contract (rewritten)
  SETUP.md                     activation, install, recovery
  ATTRIBUTION.md               browser-harness domain skills (MIT), fonts, Camoufox notices
  install-engines.sh           apt chromium + pinned Camoufox download; run by Dockerfile and migration
  cli/                         uv project, stdlib only, console script `browser`
    src/vesta_browser/
      cli.py                   argparse, one RPC per command, prints one JSON line
      protocol.py              request/response TypedDicts, error codes, state enums, caps
      serve.py                 asyncio unix-socket server, request dispatch
      lifecycle.py             daemon start|stop|restart|status per the contract
      sessions.py              session table, engine pinning, idle stop, artifact dirs
      chromium.py              Chromium launch, CDP port discovery, browser-use child, page observation
      camoufox.py              worker process supervision, pipe protocol, timeout restart
      artifacts.py             stdout path scan, containment, size/type checks, retention
      handover.py              Xvfb/openbox/x11vnc/websockify, headed engine, service + key
      doctor.py                versions, health, sessions, handover, last errors
    tests/                     the suite `check.sh agent` runs
  engines/
    chromium/                  uv project: browser-use==0.13.10 (pulls browser-harness==0.1.13)
    camoufox/                  uv project: camoufox Python lib pinned to the release matching browser tag v150.0.2-beta.25 (0.5.6b1 upstream today), playwright<1.63
      worker.py                the stealth executor; single module, run by this venv's python
  assets/handover/             noVNC page, font, image (kept)
  presets/                     Camoufox fingerprint presets (kept)
  domain-skills/               optional recipes (kept, stale files removed)
```

Runtime paths, all under the skill's own state dir:

| What | Path |
|---|---|
| pid record | `~/agent/data/daemons/browser.pid` (`<pid> <starttime>`) |
| port record | none; `status` reports `"port": null` |
| socket | `~/agent/data/browser/browser.sock`, mode 0600 |
| log | `~/agent/logs/browser.log`, append-only |
| profiles | `~/agent/data/browser/profiles/<engine>/<session>/` |
| session scratch | `~/agent/data/browser/sessions/<session>/` (the child's `TMPDIR`, Browser Harness socket and pid) |
| artifacts | `~/agent/data/browser/artifacts/<session>/<utc-timestamp>-<n>.<ext>` |
| Camoufox binary | `/opt/camoufox/<tag>/` (installed by `install-engines.sh`) |
| Chromium binary | `/usr/bin/chromium` (Debian package) |

## CLI contract

```
browser exec --session <name> [--stealth] [--timeout <secs>]     # Python on stdin
browser daemon start | stop | restart | status
browser doctor
browser engines
browser sessions
browser session stop <name>
browser stop-all
browser handover start [--url <url>] [--session <name>] [--stealth] [--minutes <n>]
browser handover status
browser handover stop
browser serve                                                    # internal foreground entry
```

Rules:

- Every command prints exactly one JSON line. Success on stdout, exit 0. Failure on stderr, exit 1, same envelope shape with `ok: false`.
- The CLI validates only what it needs to build a request (a session name is present, the timeout parses). Everything else is the daemon's.
- The CLI never imports a browser library, never starts a browser, and never starts the daemon. When the socket is absent or refuses, it fails with `error.code = "daemon_down"` and `suggested_action = "run: browser daemon start"`.
- On SIGINT or SIGTERM the CLI sends `cancel` for its in-flight request and exits 1 with `cancelled`.
- `--session` defaults to `default`. `--stealth` requests mode `stealth`; its absence on a new session requests `standard`; its absence on an existing session inherits.
- `--timeout` is clamped by the daemon to `[5, 600]` with a warning when clamped. `SKILL.md` tells Vesta to raise the Bash timeout together with `--timeout`.
- `daemon` verbs follow the contract verbatim: `{"status":"started"|"already_running"}`, `{"status":"stopped"|"already_stopped"}`, `{"running":bool,"port":null}`; `{"error":...}` on stderr and exit non-zero. `DAEMON_READY_TIMEOUT_SECS` defaults to 120, `DAEMON_STOP_TIMEOUT_SECS` to 15, both defined in `lifecycle.py`.
- The daemon writes a `daemon_died` notification on an unexpected exit and suppresses it in-process for SIGTERM.

## Daemon protocol

One JSON object per request and one per response over the unix socket, newline-delimited, `PROTOCOL_VERSION = 1`. An unknown version fails `invalid_request`.

### Request

```json
{"version": 1, "op": "exec", "request_id": "r_...", "session": "research",
 "mode": "standard" | "stealth" | null, "timeout_s": 120, "code": "..."}
```

Ops: `exec`, `cancel`, `status`, `doctor`, `engines`, `sessions`, `session_stop`, `stop_all`, `handover_start`, `handover_status`, `handover_stop`. Caps: `CODE_MAX_BYTES = 256 KiB`, `REQUEST_MAX_BYTES = 512 KiB`.

### Response envelope

```json
{
  "schema": "browser.result.v1",
  "ok": true,
  "request_id": "r_...",
  "op": "exec",
  "session": {"name": "research", "mode": "standard", "engine": "chromium",
              "protocol": "cdp", "state": "ready"},
  "page": {"state": "ready", "tab_id": "…", "url": "https://example.com/",
           "title": "Example Domain", "observed_at": "2026-09-04T12:00:00Z"},
  "output": {"stdout": "…", "stderr": "", "exit_code": 0, "duration_ms": 1240},
  "artifacts": [{"kind": "screenshot", "path": "/root/agent/data/browser/artifacts/research/20260904T120000Z-1.png",
                 "mime_type": "image/png", "bytes": 12345, "captured_at": "2026-09-04T12:00:00Z"}],
  "warnings": [],
  "error": null
}
```

- `session.state`: `starting | ready | busy | handed_over | stopped`.
- `page.state`: `ready | unavailable`. `unavailable` carries no `url`, `title`, or `tab_id`; the daemon never returns stale values from an earlier observation.
- `output.stdout` is capped at `STDOUT_CAP_BYTES = 256 KiB`, `stderr` at `STDERR_CAP_BYTES = 16 KiB`; truncation adds a warning `output_truncated`.
- `warnings` name degraded success: `output_truncated`, `timeout_clamped`, `worker_restarted`, `artifact_skipped` (with the reason), `cleanup_incomplete`.
- Non-exec ops fill `session` and `page` with `null` where they do not apply, except `sessions`, `engines`, `doctor`, and `handover_*`, whose payload rides in `data`.
- Fields never carry secrets: no service key, no cookie, no credential, no page body outside `output`.

### Error

```json
"error": {"code": "engine_capability_mismatch", "phase": "execution",
          "message": "cdp() is unavailable on camoufox; use the portable helpers or the Playwright page object",
          "retryable": false,
          "suggested_action": "change the code, or start a new standard session with a new name"}
```

Codes (closed set):

| code | phase | retryable | when |
|---|---|---|---|
| `invalid_request` | validation | no | bad version, missing field, name or code over the cap |
| `session_engine_conflict` | routing | no | explicit mode differs from the session's pinned engine |
| `engine_unavailable` | launch | yes | binary missing, browser failed to start or expose its endpoint |
| `engine_capability_mismatch` | execution | no | `cdp()` on Camoufox, `page` on Chromium |
| `execution_failed` | execution | no | the child exited non-zero for any other reason; `output.stderr` holds the traceback |
| `timed_out` | execution | yes | budget exhausted; the child was killed |
| `cancelled` | execution | no | the client sent `cancel` |
| `handover_in_use` | routing | yes | exec against a session in `handed_over` |
| `handover_failed` | handover | yes | a handover component failed its health check |
| `daemon_down` | (CLI-side) | yes | the socket is absent or refuses |

Phases: `validation | routing | launch | execution | observation | handover | cleanup`. A failure keeps every field the daemon can still verify, so Vesta tells bad code from a dead engine from a handed-over session.

## Sessions and engines

### Session table

A session record holds: name, mode, engine, protocol, state, profile dir, scratch dir, browser pid and CDP endpoint (Chromium) or worker pid (Camoufox), Browser Harness daemon pid (Chromium), in-flight request id, last activity, handover id when handed over. The table is in memory and rebuilt from disk on daemon start: a profile directory under `profiles/<engine>/<session>/` is a known session in state `stopped`. No stale processes survive a daemon restart: `lifecycle.py` places every child in a process group the daemon owns and kills the groups on stop.

Session names match `^[a-z0-9][a-z0-9_-]{0,63}$` (a subset of Browser Harness's `BU_NAME` rule, `[A-Za-z0-9_-]{1,64}`). `SESSION_IDLE_STOP_SECS = 1800`: an idle session's browser (and worker or harness daemon) is stopped, state becomes `stopped`, the profile stays. Engines start on demand: a stealth-only agent never runs Chromium.

`stop-all` stops every session of this agent and nothing else. `session stop <name>` stops one.

### Chromium (standard)

1. On first exec, launch `/usr/bin/chromium --headless=new --no-sandbox --remote-debugging-port=0 --user-data-dir=<profile> --no-first-run --disable-background-networking ...` in its own process group, `DISPLAY` unset. `--no-sandbox` is required because the container runs as root.
2. Read the port from `<profile>/DevToolsActivePort`, confirm `http://127.0.0.1:<port>/json/version`, record the endpoint. Failure → `engine_unavailable`.
3. Per exec, spawn `<engines/chromium/.venv>/bin/browser-use` with the code on stdin, cwd `artifacts/<session>/`, and a minimal env: `PATH`, `HOME`, `LANG`, `TMPDIR`, `BH_RUNTIME_DIR=sessions/<session>/runtime` (the harness socket and pid), `BH_TMP_DIR=sessions/<session>/tmp` (its screenshots), `BH_HOME=sessions/<session>/home`, `BU_NAME=<session>`, `BU_CDP_URL=http://127.0.0.1:<port>`, `BH_UPDATE_CHECK=0`, `BH_TELEMETRY=0`, `PYTHONUNBUFFERED=1`. `DISPLAY`, `PYTHONPATH`, `PYTHONHOME`, `AGENT_TOKEN`, and every other agent variable are absent. The chromium engine venv is never `uv tool install`ed: browser-use ships a console script named `browser`.
4. Browser Harness spawns its own per-`BU_NAME` daemon on first use and records its pid at `<BH_RUNTIME_DIR>/bu.pid`. The daemon reads that record and kills the harness daemon on session stop, idle stop, and daemon shutdown.
5. Timeout kills the child's process group only. The browser and harness daemon survive.
6. Page observation after every exec: `GET /json/list`, take the first `page` target, report `targetId`, `url`, `title`. Failure → `page.state = unavailable` with a warning naming the cause.

### Camoufox (stealth)

1. On first exec, spawn `<engines/camoufox/.venv>/bin/python engines/camoufox/worker.py --profile <dir> --preset <name> --artifacts <dir>` in its own process group. The worker opens the sync Camoufox API (`camoufox.sync_api.Camoufox`) with the persistent profile and the fingerprint preset (today's `presets.py` logic moves into the worker), `headless=True`, and reports `ready` on stdout. Failure → `engine_unavailable`.
2. Daemon and worker speak newline-delimited JSON over the worker's stdin and stdout: `{"op":"exec","code":...}` → `{"stdout":..., "stderr":..., "exit_code":0|1, "page":{...}}`. The worker executes each request's code with `exec(code, fresh_globals)` where `fresh_globals` holds the portable helpers, `page` (the Playwright `Page`), and a `cdp` stub that raises `CapabilityMismatch`. stdout and stderr are captured per request.
3. Timeout kills the worker's process group (Firefox is a child of the worker). The profile persists, page state is lost, the next exec restarts the worker, and the failed result carries `timed_out` while the next result carries `worker_restarted`. `SKILL.md` names this asymmetry.
4. Page observation is the worker's own `page.url` and `page.title()` after the code returns.
5. The Camoufox `omni.ja` search-stub repair stays with the installer (`install-engines.sh`) while the pinned tag still needs it, under its existing `LEGACY` marker.

## Portable helpers

Both engines expose these names with Browser Harness's signatures (Camoufox reimplements them over Playwright in `worker.py`):

```
Navigation   new_tab(url) · goto_url(url) · page_info()
Tabs         current_tab() · list_tabs() · switch_tab(id) · close_tab(id) · ensure_real_tab()
Input        click_at_xy(x, y) · type_text(text) · fill_input(selector, text) · press_key(key) · scroll(dx, dy)
Read & wait  js(expr) · wait(secs) · wait_for_load() · wait_for_element(selector) · wait_for_network_idle()
Files        capture_screenshot(path=None) · upload_file(selector, path)
```

Engine extensions:

- Chromium: every other Browser Harness helper (`cdp`, `drain_events`, `activate_tab`, `iframe_target`, `dispatch_key`, `http_get`). `page` is a stub that raises `CapabilityMismatch`.
- Camoufox: `page`, the Playwright `Page`. `cdp` is a stub that raises `CapabilityMismatch`.

`browser engines` publishes this as a versioned manifest:

```json
{"default_mode": "standard",
 "routes": {"standard": {"engine": "chromium", "protocol": "cdp", "ready": true,
                          "api": {"portable": "portable-v1", "extensions": ["browser-harness", "cdp"]},
                          "versions": {"chromium": "…", "browser-use": "0.13.10", "browser-harness": "0.1.13"}},
            "stealth":  {"engine": "camoufox", "protocol": "playwright-firefox", "ready": true,
                          "api": {"portable": "portable-v1", "extensions": ["playwright-page"]},
                          "versions": {"camoufox": "v150.0.2-beta.25", "playwright": "…"}}},
 "portable_helpers": ["new_tab", "goto_url", "…"],
 "profiles_shared_between_engines": false}
```

The portable list is one constant in `protocol.py`, asserted against the worker's globals by a test, so prose and runtime cannot drift.

## Validation and execution environment

Per exec the daemon:

1. Requires non-empty code within `CODE_MAX_BYTES`.
2. Requires a session name matching the pattern.
3. Accepts mode `standard`, `stealth`, or absent; rejects an engine change on an existing session.
4. Clamps the timeout to `[5, 600]`.
5. Refuses a session in `handed_over` (`handover_in_use`) or `busy` (`invalid_request`, one exec per session at a time).
6. Resolves the engine and confirms its binary exists before spawning anything.
7. Builds the minimal child environment described above.
8. Caps and returns stdout and stderr.

Model-written Python is a powerful surface, not a sandbox. Vesta holds Bash under `bypassPermissions`; the daemon adds no new authority class and claims no isolation. A future hostile-code posture is a separate project with its own filesystem and network policy.

## Artifacts

- Every exec runs with cwd `artifacts/<session>/`. Browser Harness's `capture_screenshot` writes under `TMPDIR`; the Camoufox worker writes straight into the artifact dir.
- After the child exits, `artifacts.py` scans stdout for image paths (`.png`, `.jpg`, `.jpeg`, `.webp`) with an mtime after exec start, exactly as Hermes does, plus every new file in the artifact dir. Each candidate is resolved, required to be under `sessions/<session>/` or `artifacts/<session>/`, checked for type by magic bytes and for size (`ARTIFACT_MAX_BYTES = 16 MiB`), moved into `artifacts/<session>/` under a timestamped name, and reported. A rejected candidate adds `artifact_skipped`.
- `ARTIFACT_RETENTION_DAYS = 7`; the daemon prunes on start and once per hour.
- A returned path means a file exists. `SKILL.md` tells Vesta to read it with the normal file tool before making any visual claim. Screenshots that are only evidence or deliverables need no read-back.

## Handover

Handover hands a session's real browser to the user for a sign-in, SSO, MFA, or an account-trust challenge. It is a daemon operation because the daemon owns both browsers and their profiles.

Flow of `handover start`:

1. Resolve `--session` (default `default`) and mode; create the session pinned to the engine when it does not exist. Refuse when a handover is already live (`handover_in_use`).
2. Stop the session's headless browser cleanly (profile lock released).
3. Claim a private Xvfb display, start openbox, x11vnc, and websockify serving the noVNC page (today's `handover.py` orchestration, moved). Screen `1280x800`; the Camoufox preset is refit with `fit_to_screen`.
4. Start the same engine headed on that display with the same profile: Chromium with `--remote-debugging-port=0` (kept for the resume step's observation), Camoufox through the worker with `headless=False`.
5. `register-service browser` (no `--public`), then `service-key mint browser --label browser-handover-<id> --ttl <lifetime>`. Lifetime is `--minutes` (default `HANDOVER_DEFAULT_MINUTES = 30`, max `HANDOVER_MAX_MINUTES = 240`); the key TTL equals it.
6. Health-check every component, then answer with `data`: `{handover_id, session, engine, state: "live", user_url, expires_at}` where `user_url = $VESTAD_PUBLIC_URL/agents/$AGENT_NAME/browser/k/<key>/handover.html`. Without `VESTAD_PUBLIC_URL` the daemon fails `handover_failed` with `suggested_action` naming the missing tunnel or LAN exposure.
7. The session enters `handed_over`; exec against it fails `handover_in_use`. The daemon takes no screenshot during handover.
8. `handover stop`, the deadline, a failed health check, or daemon shutdown: revoke the key by id, `deregister-service browser`, stop websockify, x11vnc, openbox, the headed browser, and the display, then return the session to `stopped` (the next exec restarts it headless on the same profile). Revocation and deregistration are idempotent and always attempted; a partial teardown adds `cleanup_incomplete`.

`handover status` returns `data: {state, handover_id, session, engine, user_url, expires_at}` with `state ∈ inactive | live | stopping | expired | failed`. `live` means every component passed its last health check now; an expired or unhealthy runtime is never reported `live`.

Because the daemon holds the key id, Vesta never runs `service-key` for a handover. The `/k/<key>/` path form is what lets noVNC's relative assets and WebSocket inherit the credential. The key is scoped to `browser` and opens no other service.

## Internal callers

### Maps

`browser_bridge.py` sends one program per operation to `browser exec --session default`:

```python
new_tab("https://www.google.com/maps")   # first call only; later calls switch_tab to the existing tab
wait_for_load()
print(js("(async () => { ... })()"))    # the entitylist fetch, returning the same {signed_in,status,body} envelope
```

It parses `output.stdout` as before, maps `ok: false` to `BrowserUnavailableError` with `error.message`, and stops forcing `DISPLAY`. `maps/SKILL.md` keeps its handover instruction, now `browser handover start --url "<google sign-in>"` returning `user_url`, and `browser handover stop`. `maps/SETUP.md` keeps `MAPS_BROWSER_BIN`.

### Microsoft

- One stealth session per account: `microsoft-<email-slug>`. The daemon owns the profile; `~/.microsoft/browser-profiles/` and `--user-data-dir` disappear.
- Interactive sign-in: `browser handover start --url https://outlook.office.com/mail/ --session microsoft-<slug> --stealth`, returning `user_url`; the user signs in; `browser handover stop`.
- Token capture and the unattended refresh in `monitor.py`: `browser exec --session microsoft-<slug> --stealth` running `new_tab(url); wait_for_load(); print(js(TOKEN_JS))`, polled as today. Headless. No handover, no Xvfb, no `stop-all`.
- `auth_commands.py`'s two `_run` closures are deleted; they call `capture.py`.
- Risk to verify in the live tier: Microsoft token refresh from a signed-in Camoufox profile works headless. If a tenant demands a headed browser, the fallback is a headed handover with no user, exactly today's behavior, behind one flag in `capture.py`; the spec does not build it ahead of evidence.

### Others

`flights/SKILL.md` drops `browser launch` and points at the browser skill's `exec` with `--stealth`. `agent/MEMORY.md:27` keeps its one sentence. `vestad/SKILL.md:79` and `register-service:4` stop naming browser handover as a public case.

## Skill documents

Both are written under the `vesta-prompt-guide` skill.

### `SKILL.md`

Frontmatter `description` is discovery text: when to use the browser (interactive sites, authenticated pages, JavaScript-rendered content, screenshots) and what triggers stealth (the user asks, or concrete evidence that Chromium automation is rejected). The body is operational, in this order:

1. **Choose a mode.** Standard runs Chromium. `--stealth` runs Camoufox. Different engines; no shared sessions, tabs, cookies, or profiles. A session keeps the engine it started with.
2. **Run one program.** The canonical form, once:
   ```bash
   browser exec --session <name> [--stealth] <<'PY'
   new_tab("https://example.com")
   wait_for_load()
   print(page_info())
   PY
   ```
   Put as much of one operation as practical in one execution. Browser state persists by session; Python variables do not. Raise the Bash timeout when raising `--timeout`.
3. **Helpers on both engines.** The portable list, one line per group.
4. **Engine escape hatches.** `cdp(...)` only on Chromium; `page` only on Camoufox. A mismatch returns `engine_capability_mismatch`: change the code or start a new session; never replay in the other engine.
5. **Read the result.** `ok` and `error` first, then `session.engine`, `page`, `artifacts`. A screenshot path is a file to read, not an image already seen.
6. **Handover.** One command returns `user_url`; send that URL alone; `browser handover stop` when the user is done. Never share a local port.
7. **Recovery.** `browser doctor`, `browser engines`, `browser sessions`, `browser daemon start`.

No engine internals, dependency pins, socket paths, or provider talk. Examples show the shared helpers once, never the same workflow twice per engine. Domain recipes stay as optional references linked at the end.

### `SETUP.md`

Read once at activation: `uv tool install --editable ~/agent/skills/browser/cli`; `uv sync --frozen --project ~/agent/skills/browser/engines/chromium` and the same for `camoufox`; confirm `/usr/bin/chromium` and `/opt/camoufox/<tag>` exist (run `~/agent/skills/browser/install-engines.sh` when they do not); `browser daemon start`; add `browser daemon start` to `~/agent/skills/restart/daemons.sh`; `browser doctor` to confirm both routes `ready`. Also: the runtime paths table, handover requirements (`VESTAD_PUBLIC_URL`), and recovery steps. It never tells Vesta to install anything during a task.

## Packaging and fleet migration

### Image (`vestad/Dockerfile`)

- A commented apt layer adds `chromium` (Debian trixie, both architectures). The existing Gecko libs and handover packages stay.
- `RUN /root/agent/skills/browser/install-engines.sh` after the agent home is copied: installs Camoufox `<tag>` for the build architecture into `/opt/camoufox/<tag>/` with sha256 verification, applies the search-stub repair, and is a no-op when the tag is present.
- No venv is built here (convention), so a fresh agent's first `SETUP.md` pass runs the `uv` steps like every other skill.

### Migration (`agent/core/migrations/2026-09-browser-daemon.md`, after_sync, non-interruptible)

Idempotent steps, each safe to rerun:

1. Run `~/agent/skills/browser/install-engines.sh` (apt chromium; Camoufox to `/opt`).
2. `uv tool install --editable --force ~/agent/skills/browser/cli`; `uv sync --frozen` on both engine projects.
3. Stop any old runtime: kill processes whose argv matches `vesta_browser.daemon` or the old Camoufox launch shape; remove `/tmp/vesta-browser-*` and `~/.cache/camoufox`.
4. Move `~/.microsoft/browser-profiles/<email>` to `~/agent/data/browser/profiles/camoufox/microsoft-<slug>/` (same engine, same profile format), when present.
5. Replace any `browser` line in `daemons.sh` with `browser daemon start`; add it when absent.
6. `browser daemon start`, `browser doctor`; `mark_migration_applied`.

Fresh agents pre-mark it. Tracked file changes (skill docs, CLI code) reach the fleet through upstream sync; the migration exists only for the system packages, the venvs, the moved profiles, and the old processes.

## Repo integration

- `agent/tests/test_daemon_contract.py`: add `Daemon(command=["uv", "run", "--project", str(SKILLS_DIR / "browser/cli"), "browser"], name="browser", serves_port=False, emits_daemon_died=True)`, the same form as the `google` row.
- `agent/tests/test_service_exposure.py`: remove `browser/cli/src/vesta_browser/handover.py` from `EXPECTED_DIRECT_PUBLIC`.
- `AGENTS.md`: the public-service list loses the browser handover page (lines naming the four public services and the `--public` pins); the skill section gains one paragraph on the browser daemon.
- `agent/skills/vestad/scripts/register-service:4` comment and `vestad/SKILL.md:79` example: stop citing browser as public.
- `check.sh guards` lockfile freshness: confirm `engines/chromium/uv.lock` and `engines/camoufox/uv.lock` are covered; extend the glob when they are not.
- `ATTRIBUTION.md`: keep the browser-harness domain-skill notice; add Browser Use (MIT), Browser Harness (MIT), Camoufox Python (MIT) and browser (MPL 2.0) notices.
- `agent/core/default-skills.txt`: unchanged.

## Retired and kept

Deleted in the same release: `admin.py`, `bidi.py`, `cdp_backend.py`, `daemon.py` (old), `helpers.py`, `launcher.py` (its download, hash, and repair logic move into `install-engines.sh`; its Xvfb and display logic into the new `handover.py`; its fingerprint env into `worker.py`), `snapshot.py`, `vendor/walker.js`, `vendor/snapshot_accname.js`, the 31 old subcommands, semantic refs, the raw `bidi` command, `interaction-skills/profile-sync.md`, and the `browser-harness/1.0` stale mentions in domain recipes.

Kept: the skill directory and activation, the `browser` command name, `assets/handover/`, `presets/`, `domain-skills/` as optional references, `ATTRIBUTION.md`.

## Testing

Fast tier (`cli/tests`, hermetic, no browser binary):

- `protocol`: every op round-trips; unknown version, oversized code, bad session name → `invalid_request`; every error code carries `phase`, `retryable`, `suggested_action`.
- `sessions`: engine pinning, `session_engine_conflict`, inheritance, idle stop, rebuild from profile dirs, one exec per session.
- `chromium`: launch argv, `DevToolsActivePort` discovery against a fake, minimal child env (asserts `PYTHONPATH`, `DISPLAY`, `AGENT_TOKEN` absent), timeout kills the child group and not the browser, page observation from a fake `/json/list`, `unavailable` on failure.
- `camoufox`: pipe protocol against `worker.py` driven with a fake `page`, fresh globals per request, `cdp` stub → `engine_capability_mismatch`, timeout restarts the worker and warns, portable-helper list equals `protocol.PORTABLE_HELPERS`.
- `artifacts`: stdout path scan, containment (a path outside the session dirs is skipped with a warning), size and magic-byte checks, timestamped move, retention prune.
- `handover`: component order, health-check gating of `live`, private registration (`--public` never passed), key mint with TTL = lifetime, revoke + deregister on stop, expiry, failure, and shutdown, `handover_in_use` on exec, cleanup warnings, refusal without `VESTAD_PUBLIC_URL`.
- `cli`: one JSON line per command, stdout/stderr by outcome, `daemon_down`, SIGINT → `cancel`.
- `lifecycle`: the daemon-contract row in `agent/tests/test_daemon_contract.py`.
- Maps and Microsoft suites: their `browser` shims answer the `exec` shape; capture tests cover the per-account session names and the headless refresh path.

Live tier (`check.sh live`, real binaries, marked and skipped when absent): one standard exec with a screenshot read back, one stealth exec, engine pinning end to end, a handover start/status/stop cycle asserting the key is revoked and the service deregistered, and the Microsoft headless refresh against a signed-in profile fixture where credentials allow.

## Delivery

One epic branch, three stacked PRs reviewed in order and released together, because the fleet must never run a release where callers and runtime disagree:

1. `feat(skills/browser): browser daemon with chromium and camoufox executors`: `cli/`, `engines/`, `install-engines.sh`, Dockerfile layer, tests, daemon-contract row. The old runtime is deleted here, because one console script and one package cannot hold both; between PR 1 and PR 3 the tree's callers point at commands that no longer exist, which is why the three PRs release together.
2. `feat(skills/browser): private handover through the daemon`: `handover.py`, service-exposure and AGENTS.md updates.
3. `refactor(skills): move browser callers to browser exec, rewrite the skill, retire the old runtime`: `SKILL.md`, `SETUP.md`, maps, microsoft, flights, MEMORY.md, the migration, deletions.

`MIN_SUPPORTED_CLIENT_VERSION` is untouched: no client wire shape changes.

## Out of scope

- Cloud backends (Browser Use Cloud, Browserbase, Firecrawl) and Lightpanda. The `mode → engine → backend` routing leaves room; `browser engines` already reports a `backend` field fixed at `local`.
- A sandbox for model-written Python.
- Copying a host browser profile (Hermes' `local`): needs a host mount or service and breaks per-container isolation.
- `writing/gptzero.py`'s private Chromium stack; a follow-up can point it at the daemon.
- Viewer detection during handover.

## Sources

- Hermes `tools/browser_use_cli.py`, `agent/browser_registry.py` @ `63279301bcbdc185c1b07b98a9312eb0c862f26d`
- Browser Use `pyproject.toml`, `browser_use/cli.py`, `browser_use/browser/session.py`, `skills/browser-use/SKILL.md` @ `fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a`
- Browser Harness `README.md`, `install.md`, `src/browser_harness/{helpers,daemon,run}.py`, `LICENSE` @ `10b2086c29f0696a6712956d2914e03012f5ebd0`
- Camoufox `pythonlib/pyproject.toml`, `README.md`, https://camoufox.com/python/usage/, https://camoufox.com/python/remote-server/
- This repo @ `f909df0d`: `agent/skills/browser/**`, `agent/skills/maps/cli/src/gmaps_cli/browser_bridge.py`, `agent/skills/microsoft/cli/src/microsoft_cli/{capture,auth_commands,monitor}.py`, `agent/skills/vestad/**`, `agent/tests/{test_daemon_contract,test_service_exposure}.py`, `vestad/src/{service_keys,agent_proxy,docker}.rs`, `vestad/Dockerfile`
