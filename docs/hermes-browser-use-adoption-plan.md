# Hermes Browser Runtime with a Vesta Skill and Browser Daemon

Status: revised replacement architecture  
Review date: 2026-09-04  
Local revision: `a5c52c560dcf504fcd6226239d160c8434e70c63`  
Hermes revision: [`6327930`](https://github.com/NousResearch/hermes-agent/tree/63279301bcbdc185c1b07b98a9312eb0c862f26d)  
Browser Harness revision: [`10b2086`](https://github.com/browser-use/browser-harness/tree/10b2086c29f0696a6712956d2914e03012f5ebd0)  
Browser Use revision: [`fe5ad35`](https://github.com/browser-use/browser-use/tree/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a)

This is a separate architecture report. The [functional overview](./browser-agent-functional-overview.md) explains the current relationship between Claude, the skill, the CLI, and the browser. The [technical comparison](./browser-skill-technical-comparison.md) audits the current implementation against Hermes and Browser Use CLI 3.0.

This revision records the chosen boundary: keep the ordinary Vesta skill model and do not add a native Claude Agent SDK browser tool. Claude reads `SKILL.md`, invokes a `browser` CLI through its existing Bash tool, and that CLI talks to a browser harness daemon built and run inside the agent container.

## Executive decision

Adopt Hermes' browser execution behavior while retaining the repository's normal skill interface.

The end state is:

1. The browser remains a disk-backed skill with [`SKILL.md`](../agent/skills/browser/SKILL.md) and [`SETUP.md`](../agent/skills/browser/SETUP.md).
2. Claude loads the skill when browsing is needed.
3. Claude uses its existing Bash tool to call `browser exec` with Python on stdin.
4. The `browser` executable is both the public CLI and the owner of `browser daemon start|stop|restart|status`.
5. The browser daemon owns validation, engine and backend routing, workspace allocation, screenshot handling, session supervision, browser processes, execution workers, timeouts, cleanup, diagnostics, and handover.
6. Standard mode invokes the pinned Browser Use CLI execution path and uses upstream Browser Harness for CDP helpers and persistent browser state.
7. Stealth mode invokes a Camoufox executor managed by the same daemon. It uses Firefox automation rather than trying to send CDP to Camoufox.
8. Container-managed Chromium is the default engine; Camoufox is selected explicitly when stealth is required.
9. Maps, Microsoft, handover, and Claude all reach both engines through the same daemon.
10. The current action engine and CDP translation layer are retired. Its Camoufox launch, profile, fingerprint, and Firefox-transport lessons feed the new stealth adapter; raw BiDi remains only until the Playwright worker reaches parity.
11. No browser-specific tool is registered in [`core/tools.py`](../agent/core/tools.py), and dormant `agent/core/cc_sdk/` remains untouched.

This preserves almost all of the Hermes runtime model but intentionally does not copy its model-facing integration boundary. Hermes exposes a native `browser_exec` tool. The chosen design exposes an ordinary skill and CLI, consistent with the other capabilities in this repository.

## Target architecture

```text
User message, notification, or scheduled work
                       |
                       v
              agent harness turn
                       |
                       v
             Claude loads SKILL.md
                       |
                       v
         Claude calls Bash: browser exec
                       |
                       v
             thin browser CLI client
                       |
              private Unix socket
                       v
       Vesta-run browser daemon
       validation, engine routing, workspaces,
       screenshots, sessions, timeout,
       browser lifecycle, handover
                       |
             +---------+---------+
             |                   |
             v                   v
        standard mode        stealth mode
       Browser Use CLI      Camoufox executor
             |                   |
             v                   v
       Browser Harness     Playwright Firefox
             |                   |
             v                   |
       Chromium over CDP          v
                            Camoufox

Optional standard-mode routes:
explicit CDP, Lightpanda, Browser Use Cloud,
Browserbase, or Firecrawl
```

Claude remains the planner. The browser daemon is not another agent and does not choose browsing goals. It executes and supervises browser programs submitted by Claude or other authorized local callers.

## How this differs from Hermes

```text
Hermes:
model -> native browser_exec -> Hermes adapter -> Browser Use CLI

Chosen design:
Claude -> SKILL.md -> Bash -> browser CLI -> browser daemon -> Browser Use CLI
```

The behavior after the model request should closely follow Hermes. The difference is where the adapter lives and how Claude reaches it.

| Concern | Hermes | Chosen design |
|---|---|---|
| Model discovery | Native tool description | On-demand `SKILL.md` |
| Model invocation | Structured tool call | `browser` through Bash |
| Browser control plane | Hermes process adapter | Long-lived browser daemon |
| Shared access for other skill CLIs | Separate integration required | Same daemon protocol |
| Screenshot delivery | Native multimodal tool result | Artifact path returned through Bash, then read with Claude's file tool |
| Agent core changes | Native tool registration | None beyond existing skill discovery |

The main gain is architectural consistency with the rest of the repository. The main cost is that Bash can return text but cannot directly emit a Claude SDK image content block.

## Protocol constraint and dual-executor decision

Camoufox cannot be inserted as another Browser Harness CDP endpoint. Upstream Browser Harness describes itself as a direct CDP harness for Chrome or Chromium, and Browser Use's current browser session is built around `cdp-use`. Camoufox is a Firefox fork exposed through Playwright's Firefox protocol or WebDriver BiDi. See the [Browser Harness architecture](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/install.md), [Browser Use session implementation](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/browser_use/browser/session.py), and [official Camoufox Playwright usage](https://camoufox.com/python/usage/).

It follows that one daemon needs two executor adapters:

| Mode | Executor | Browser protocol | Capability |
|---|---|---|---|
| Standard | Pinned Browser Use CLI and upstream Browser Harness | CDP | Full Browser Use CLI 3.0 execution surface |
| Stealth | Vesta Camoufox executor | Official in-process Playwright Firefox API | Camoufox fingerprinting and a compatible high-level helper surface |

This is an architectural inference from the upstream protocol boundaries. It avoids two fragile alternatives: maintaining a fork of Browser Use under the same import name, or building a complete CDP-to-Firefox protocol translator.

The Camoufox executor should implement the portable high-level Browser Harness operations Claude uses most: tabs, navigation, page information, JavaScript, click, type, fill, keys, scrolling, waits, screenshots, uploads, and downloads. It can expose the Playwright `page` object as its engine-specific escape hatch. Raw CDP calls remain standard-mode only, while raw BiDi or Playwright calls remain stealth-mode only.

Therefore, “full Browser Use CLI 3.0” remains exactly true for standard mode. Stealth mode is intentionally a compatible Vesta executor, not a false claim that upstream Browser Use supports Firefox.

## Ownership rule

If a decision is browser-specific, the browser daemon owns it. The skill explains the interface, and ordinary commands transport requests. Neither contains a second browser implementation.

| Capability | Browser daemon responsibility | Skill or CLI responsibility |
|---|---|---|
| Validation | Validate code, session, timeout, workspace identifier, URLs, and backend policy | CLI validates only enough to form an RPC request |
| Engine and backend routing | Select standard or stealth execution, then provision, health-check, and tear down the configured local or cloud backend | Skill expresses the need for stealth; it does not choose protocols |
| Workspace allocation | Create stable, contained artifact directories and return opaque workspace ids | Claude may reuse a returned workspace id on a later call |
| Screenshot handling | Discover, validate, classify, size-limit, and persist screenshots | CLI prints the trusted path; skill tells Claude to read it when visual inspection is needed |
| Session supervision | Own logical sessions, tabs, Browser Harness or Camoufox workers, browser connections, expiry, and cleanup | Claude supplies a meaningful session name and optional stealth intent |
| Execution | Build the child environment and invoke the pinned Browser Use CLI | CLI sends Python source over RPC |
| Handover | Coordinate the selected engine's profile, headed browser, noVNC, vestad registration, expiry, and cleanup | CLI exposes start, status, and stop commands |
| Diagnostics | Report versions, process health, sessions, workspaces, and last failures | `browser doctor` renders the daemon response |

This single-owner rule matters because Claude is not the only consumer. Maps and Microsoft already call the browser executable from their own processes. Putting policy in a native Claude tool would make those callers bypass it or require duplicated code.

## Skill and setup contract

### `SKILL.md`

`SKILL.md` remains the model-facing browser contract. It should become shorter than the current action-oriented guide while remaining complete enough for Claude to use the new executor without guessing.

It should explain:

* Use `browser exec` for interactive sites, authenticated pages, screenshots, and JavaScript-rendered content.
* Supply a complete browser operation as Python on stdin whenever practical.
* There are two genuinely different engines, not two names for the same browser: Chromium uses Browser Use CLI and CDP; Camoufox uses Firefox through the Vesta Camoufox executor and Playwright.
* Use standard mode and Chromium by default. Request stealth mode and Camoufox only when the user asks for it or there is concrete evidence that ordinary Chromium automation is being rejected.
* A session is pinned to the engine chosen on its first call. Switching to Camoufox requires a new session name and does not copy cookies, tabs, profiles, or prior actions.
* Full Browser Use and raw CDP helpers belong to Chromium. Camoufox guarantees the documented portable helpers and provides a Playwright `page` escape hatch. Never assume an engine-specific operation exists on the other engine.
* Browser and page state persist by named session.
* Python variables exist for one execution only.
* A workspace is for artifacts, while a session is for browser continuity.
* The first call returns a workspace id. Reuse it only when later calls belong to the same user task.
* Screenshots are saved and returned as paths. Use Claude's file-reading capability to inspect one visually.
* Handover is the path for user-entered credentials, SSO, MFA, and account-trust challenges.
* Handover registers the `browser` service privately. After starting it, mint a short-lived key with `service-key mint browser`, build the path-keyed URL, and share only that URL with the user.
* When handover finishes, stop it and revoke the key. Never register handover with `--public`, never share the raw local port, and never use the agent token as a proxy credential.
* `browser doctor` is the first diagnostic command when the daemon or browser is unavailable.
* The CLI output is structured and should be checked for `ok`, `error`, and artifact fields.

The skill can include the same compact Browser Harness helper digest Hermes places in its native tool description. This preserves the useful part of Hermes' interface without registering a tool. Long domain recipes should be optional references, not automatically loaded for every browser task.

### Required model-facing structure

The actual `SKILL.md` must be operational rather than architectural. It should use short imperative instructions, one canonical command form, and progressive disclosure in this order:

1. Decide whether a browser is needed.
2. Choose standard or stealth mode.
3. Run one complete program with `browser exec`.
4. Use the shared portable helpers.
5. Inspect the structured result and any screenshot path.
6. Read the engine-specific section only when a portable helper is insufficient.
7. Use handover only when the user must interact.
8. Use `browser doctor` only for recovery.

Its normal-use core should be no more complicated than:

```markdown
## Choose a mode

Use standard mode by default. It runs Chromium.
Use `--stealth` only when stealth is required. It runs Camoufox.
They are different engines and do not share sessions, tabs, cookies, or profiles.

## Run browser code

browser exec --session <name> [--stealth] <<'PY'
new_tab("https://example.com")
print(page_info())
PY

Reuse the same session name to keep browser state. Use a new session name to
change engines. Put as much of one operation as practical in one execution.

## Helpers available on both engines

Navigation: new_tab, goto_url, page_info
Tabs: current_tab, list_tabs, switch_tab, close_tab, ensure_real_tab
Input: click_at_xy, type_text, fill_input, press_key, scroll
Read and wait: js, wait, wait_for_load, wait_for_element, wait_for_network_idle
Files: capture_screenshot, upload_file

## Engine-specific escape hatches

Use `cdp(...)` only on Chromium.
Use the Playwright `page` object only on Camoufox.
Prefer the shared helpers. Never silently switch engines or replay an action.

## Read every result in this order

1. `ok` and `error`: did the operation succeed, and what should happen next?
2. `context.session`: which session and engine actually ran?
3. `context.execution`: what operation is running or finished?
4. `context.page`: which tab, URL, and title are current?
5. `context.page.visual`: is the screenshot current, stale, or absent?
6. `context.handover`: is handover live, is user access active, and is a viewer connected?

A screenshot path means the image was captured, not that you have seen it. Read the
file with the normal file tool before making a visual claim.
```

The final skill should add only compact result handling, handover, and recovery sections after this core. Daemon internals, provider precedence, process supervision, dependency pins, socket paths, and protocol design belong in `SETUP.md` or implementation documentation, not in Claude's normal browsing instructions.

Examples should demonstrate the shared API first. Do not show two copies of an ordinary workflow, one for each engine, because that incorrectly teaches Claude that routine browser code must branch by engine. Engine-specific examples belong under clearly labeled advanced headings.

### Engine vocabulary taught to Claude

The design uses the following terms consistently:

| Term | Meaning | Values |
|---|---|---|
| Mode | The capability Claude requests | `standard`, `stealth` |
| Engine | The browser implementation the daemon selects | `chromium`, `camoufox` |
| Backend | Where that engine runs or who provides it | `local`, explicit CDP, Browser Use Cloud, Browserbase, Firecrawl |
| Protocol | How the engine adapter controls the browser | CDP for Chromium, Playwright Firefox for Camoufox |

Only mode and engine belong in the main execution instructions. Backend and protocol appear in structured output and the advanced troubleshooting reference; Claude does not normally choose either one. This keeps the everyday rule to two lines: omit `--stealth` for Chromium, or add `--stealth` for Camoufox.

Claude requests a mode, while the daemon resolves and reports the engine. The initial policy is `standard -> chromium` and `stealth -> camoufox`. The distinction remains explicit because a future stealth cloud backend could satisfy the same mode with another engine.

The skill should never describe Camoufox as “Browser Use in stealth mode.” It is a separate engine behind the same daemon, with a deliberately compatible high-level surface.

When Claude is uncertain, `SKILL.md` should tell it to run `browser engines` before writing browser code. Every engine-bound result, including failures, should repeat the resolved mode, engine, backend, protocol, portable API version, and engine extensions. Claude must use those returned fields as the source of truth rather than infer the engine from a session name or assume that `--stealth` means Chromium with extra flags.

### `SETUP.md`

`SETUP.md` is read once when the skill is activated, and again when setup or recovery is needed. It is not loaded for every ordinary browser task. It should document:

* Pinned Browser Use, Browser Harness, Chromium, and Camoufox versions.
* Image packages and architecture support.
* Daemon socket, state, profile, workspace, and log locations.
* Backend configuration and provider credential names.
* Browser and daemon startup behavior.
* The idempotent `browser daemon start` command and restart-skill entry.
* Handover dependencies and gateway requirements.
* Doctor output and recovery procedures.
* The deliberate lack of host-profile copying inside Docker.

Normal image builds should already contain every required dependency. `SETUP.md` must not instruct Vesta to install packages dynamically during a task.

## CLI contract

The model-facing command should be small:

```text
browser exec \
  --session <name> \
  [--workspace <id>] \
  [--stealth] \
  [--timeout <seconds>]
```

Python arrives on stdin. The CLI sends one RPC request and prints one structured response. `--stealth` expresses the required capability; the daemon resolves it to Camoufox according to policy. The CLI does not import a browser driver, select a protocol or provider, allocate paths, or start cloud sessions itself.

The supporting commands should be:

```text
browser daemon start
browser daemon stop
browser daemon restart
browser daemon status
browser doctor
browser engines
browser sessions
browser session stop <name>
browser stop-all
browser handover start [--url <url>] [--session <name>] [--stealth]
browser handover status
browser handover stop
```

Legacy commands needed temporarily by Maps or Microsoft may remain as compatibility translations, but they must call the browser daemon. They must not retain an independent driver or daemon.

`browser engines` prints the current routing and capabilities as structured JSON. It should identify the default mode, available engines, protocol, helper surface, profile separation, readiness, and any unavailable dependency. `browser sessions` prints each session's mode, resolved engine, backend, protocol, and last activity. These commands let Claude verify reality instead of relying only on remembered instructions.

The `data` portion of its standard result envelope should look like this:

```json
{
  "default_mode": "standard",
  "routes": {
    "standard": {
      "engine": "chromium",
      "protocol": "cdp",
      "api": {
        "portable": "portable-v1",
        "extensions": ["browser-use-cli-3.0", "cdp"]
      },
      "ready": true
    },
    "stealth": {
      "engine": "camoufox",
      "protocol": "playwright-firefox",
      "api": {
        "portable": "portable-v1",
        "extensions": ["playwright-page"]
      },
      "ready": true
    }
  },
  "profiles_shared_between_engines": false
}
```

The exact helper manifest should also be machine-readable in this response, either inline or under a versioned `capabilities` object. That keeps the prose and runtime from drifting when one executor gains a feature.

This follows the repository-wide daemon contract documented by the `skills-registry` and `vestad` skills. `browser daemon start` is idempotent and exclusive, returns only when the daemon is ready, and prints one line of JSON. Stop uses SIGTERM as the deliberate shutdown and applies the standard bounded fallback. Status reads the local process record and prints one line of JSON.

The internal foreground entry point should be `browser serve`. Claude is instructed to manage it only through `browser daemon start|stop|restart|status`, just as it uses `tasks daemon ...`, `slack daemon ...`, and `app-chat daemon ...` rather than launching their `serve` commands.

The browser daemon uses the standard locations:

* PID record: `~/agent/data/daemons/browser.pid`
* Port record: none, because normal control uses a Unix socket; daemon status reports `"port": null`
* Socket: `~/agent/data/daemons/browser.sock`
* Append-only startup log: `~/agent/logs/browser.log`

`SETUP.md` adds the bare `browser daemon start` line to the restart skill's daemon list. An ordinary browser command that finds the daemon down should fail clearly and say to run `browser daemon start`; it should not create an undocumented second lifecycle path.

## Daemon protocol

The browser daemon should expose a small versioned RPC protocol over a mode-`0600` Unix socket. A primary request is conceptually:

```json
{
  "version": 1,
  "op": "exec",
  "request_id": "...",
  "code": "...",
  "session": "research",
  "workspace": null,
  "mode": "standard",
  "timeout_s": 300
}
```

The daemon allocates a workspace when `workspace` is absent. Every command returns the same top-level result shape. An execution response is conceptually:

```json
{
  "schema": "browser.result.v1",
  "ok": true,
  "request_id": "...",
  "operation": "exec",
  "workspace": "w_01...",
  "data": null,
  "context": {
    "session": {
      "name": "research",
      "state": "ready",
      "control_owner": "agent",
      "mode": "standard",
      "engine": "chromium",
      "backend": "local",
      "protocol": "cdp",
      "api": {
        "portable": "portable-v1",
        "extensions": ["browser-use-cli-3.0", "cdp"]
      }
    },
    "execution": {
      "state": "completed",
      "exit_code": 0,
      "duration_ms": 1240,
      "timeout_s": 300,
      "current_action": null,
      "last_action": {
        "sequence": 5,
        "name": "capture_screenshot",
        "state": "completed"
      },
      "action_count": 5
    },
    "page": {
      "state": "ready",
      "tab_id": "tab_01...",
      "url": "https://example.com/",
      "title": "Example Domain",
      "ready_state": "complete",
      "dialog": null,
      "observed_at": "2026-09-04T12:00:00Z",
      "visual": {
        "state": "current",
        "artifact_id": "artifact_01..."
      }
    },
    "handover": {
      "state": "inactive",
      "live": false,
      "private_service": "not_registered",
      "user_access": "missing",
      "viewer_connected": false
    }
  },
  "output": {
    "stdout": "...",
    "stderr": ""
  },
  "artifacts": [
    {
      "id": "artifact_01...",
      "kind": "screenshot",
      "path": "/.../shot.png",
      "mime_type": "image/png",
      "size": 12345,
      "captured_at": "2026-09-04T12:00:00Z"
    }
  ],
  "warnings": [],
  "error": null
}
```

Additional operations should cover `cancel`, `status`, `doctor`, `engines`, `sessions`, `session_stop`, `stop_all`, `handover_start`, `handover_status`, and `handover_stop`.

Every success and error uses this envelope. Components that do not apply still report an explicit state such as `inactive`, `none`, or `unavailable`; callers should never have to infer state from a missing field. A known operation from the wrong engine must not degrade to a generic Python failure or silently choose another engine. Its `error` should be actionable, for example:

```json
{
  "schema": "browser.result.v1",
  "ok": false,
  "request_id": "...",
  "operation": "exec",
  "workspace": "w_01...",
  "data": null,
  "context": {
    "session": {
      "name": "research-cf",
      "state": "ready",
      "control_owner": "agent",
      "mode": "stealth",
      "engine": "camoufox",
      "backend": "local",
      "protocol": "playwright-firefox",
      "api": {
        "portable": "portable-v1",
        "extensions": ["playwright-page"]
      }
    },
    "execution": {
      "state": "failed",
      "current_action": null,
      "last_action": {"sequence": 1, "name": "cdp", "state": "rejected"},
      "action_count": 1
    },
    "page": {"state": "unavailable", "visual": {"state": "absent"}},
    "handover": {"state": "inactive", "live": false, "private_service": "not_registered", "user_access": "missing", "viewer_connected": false}
  },
  "output": {"stdout": "", "stderr": ""},
  "error": {
    "code": "engine_capability_mismatch",
    "phase": "validation",
    "operation": "cdp",
    "available_on": ["chromium"],
    "message": "Raw CDP is unavailable on Camoufox; use the portable helpers or the Playwright page API.",
    "retryable": false,
    "suggested_action": "Change the code, or deliberately start a new Chromium session."
  },
  "warnings": [],
  "artifacts": []
}
```

The daemon should maintain a versioned capability manifest for each executor. It can preflight recognized engine-specific helpers and must normalize adapter-level capability failures to `engine_capability_mismatch`. Dynamic Python can still fail normally, but it must never cause transparent cross-engine fallback.

### Runtime truth and state semantics

The result envelope is the single source of truth for Claude, internal skill callers, diagnostics, and future clients. Human prose may summarize it, but must not replace or contradict it.

The state fields have closed meanings:

* Session state: `starting`, `ready`, `busy`, `handed_over`, `stopping`, `stopped`, `failed`.
* Control owner: `agent`, `handover_user`, `none`.
* Execution state: `queued`, `running`, `completed`, `failed`, `timed_out`, `cancelled`.
* Page state: `none`, `loading`, `ready`, `dialog`, `closed`, `unavailable`.
* Visual state: `current`, `stale`, `absent`.
* Handover state: `inactive`, `starting`, `live`, `stopping`, `failed`, `expired`.
* Private-service state: `not_registered`, `registered_private`, `unhealthy`, `unknown`.
* User-access state: `missing`, `active`, `unknown`.

The daemon refreshes the final page observation after every execution, including a failed or timed-out one when the worker remains reachable. It returns the active opaque tab id, URL, title, document readiness, pending dialog metadata, and observation timestamp. If it cannot observe the page, it says `unavailable` and retains no apparently current values from an older observation.

Portable helper calls update a safe execution marker. While work is running, `current_action` names the helper in progress. Afterward, `last_action` and `action_count` identify how far the program reached. The marker records no typed text, cookies, page bodies, source code, or raw arguments. An engine escape hatch is labeled `cdp` or `playwright-page` without logging its sensitive payload. `browser sessions` exposes the same marker for an active execution.

Visual truth is stricter. A screenshot is `current` only when it was captured after the last page-changing helper in that request. Navigation, input, scrolling, tab changes, JavaScript with possible side effects, dialogs, timeout, or an external handover interaction mark an earlier screenshot `stale`. `absent` means no screenshot belongs to the current page state. The daemon returns the matching artifact id, but only Claude's later file-read operation means the model has actually seen the pixels.

Errors always contain `code`, `phase`, `message`, `retryable`, and `suggested_action`. The phase is one of `validation`, `routing`, `launch`, `execution`, `observation`, `handover`, or `cleanup`. A failure preserves all context the daemon can still verify, so Claude can distinguish bad code from a dead engine, a changed page, an expired handover, and a cleanup warning.

Warnings describe degraded but successful behavior and never carry the primary failure. Output truncation, a stale visual observation, a worker restart, or incomplete cleanup must be named explicitly rather than hidden in stderr.

Every artifact path returned by the daemon must already be resolved, contained under its workspace root, and checked for size and type. The CLI treats it as opaque output and does not search the filesystem for screenshots.

The protocol should have explicit maximum request, output, and artifact sizes. Unknown protocol versions fail clearly. A client disconnect does not automatically abandon an execution: the CLI sends `cancel` when its Bash process is interrupted, while the daemon applies the configured policy if the client disappears unexpectedly.

## Validation

Validation remains part of the desired design, but it lives in the browser daemon.

For every execution the daemon should:

1. Require non-empty Python within a configured size limit.
2. Require a session name with a small, path-independent character set and length bound.
3. Accept only `standard` or `stealth` mode and reject an engine change on an existing session.
4. Bound the timeout, retaining Hermes' reviewed range of 5 through 1800 seconds unless operational evidence justifies another limit.
5. Validate a supplied workspace as an opaque daemon-issued identifier.
6. Scan literal URLs for unsafe schemes and prohibited local targets.
7. Resolve the selected engine, backend, and required credentials before spawning work.
8. Build a minimal child environment.
9. Remove `PYTHONPATH`, `PYTHONHOME`, and unrelated agent secrets.
10. Cap and sanitize stdout and stderr.

The literal URL scan is early feedback and defense in depth. Model-written Python can construct URLs dynamically and can use ordinary networking libraries, so this validation is not a sandbox.

## Backend routing

Routing has two stages. First the daemon resolves the requested capability mode to an engine. Then it resolves that engine to a local or remote backend.

Initial mode policy:

1. `standard` resolves to Chromium.
2. `stealth` resolves to local Camoufox.
3. An administrator may later configure an explicit stealth-capable cloud backend, but the daemon still reports the engine actually selected.

Recommended standard-mode backend precedence follows Hermes:

1. An explicit Browser Use endpoint override for controlled development.
2. An explicit CDP endpoint configured for the agent.
3. A selected cloud provider.
4. Lightpanda when explicitly selected for compatible, non-visual work.
5. Supervised container Chromium as the default.

Optional providers can include Browser Use Cloud, Browserbase, and Firecrawl. A Nous-specific gateway should not be copied unless separately selected as a supported provider.

Provider sessions have explicit create, expiry, and teardown ownership in the daemon. Credentials come from the agent's secret environment or secret store and never appear in CLI output, logs, or workspaces.

The daemon must never automatically replay a failed standard execution in Camoufox. Browser actions may submit forms, send messages, or make purchases, and replaying them is not generally safe. Claude evaluates the failure and starts a new named stealth session explicitly. Changing engines also changes cookies and page state.

## Workspace allocation

Without a native SDK tool, the browser subsystem does not automatically know the harness' current turn identity. The daemon should therefore issue opaque workspace ids itself.

The normal flow is:

1. Claude starts a browser task without `--workspace`.
2. The browser daemon creates a new workspace and returns its id.
3. A complete one-call browser program needs no further bookkeeping.
4. If another call belongs to the same task, Claude passes the returned id through `--workspace`.
5. The daemon expires inactive workspaces according to retention policy while preserving artifacts long enough for the task to consume them.

This keeps allocation inside the daemon and avoids changes to [`QueuedTurn`](../agent/core/models.py). Session and workspace identifiers must remain separate. Reusing a browser session preserves login and page state; reusing a workspace groups files for one task.

## Screenshot handling

The browser daemon owns screenshot discovery and artifact safety:

* Detect screenshots created through Browser Harness or Camoufox helpers.
* Normalize output locations into the active workspace.
* Validate image type, dimensions, and file size.
* Return structured artifact metadata and a trusted path.
* Retain or delete artifacts according to workspace policy.

The chosen skill interface cannot provide automatic native image attachment. Bash tool output is text. When visual inspection is needed, `SKILL.md` tells Claude to read the returned screenshot path using its normal file capability. This introduces one additional tool step compared with Hermes, but no browser-specific SDK integration.

Screenshots that are only evidence or user deliverables do not need to be read back into the model. The structured result still makes their paths available for later use.

## Session supervision

The browser daemon owns the logical session table. A session record should track:

* Session name and last activity.
* Requested mode and resolved engine.
* Backend and provider session identity.
* Browser Harness or Camoufox worker process and health.
* Current browser endpoint and protocol.
* Owned tab or context.
* Associated profile where applicable.
* Active execution request.
* Expiry and cleanup state.

Browser state persists across CLI calls because the daemon and engine worker remain alive. Python variables do not persist because each `browser exec` receives fresh execution globals. Named standard sessions should receive Hermes' own-tab protection when several sessions share one Chromium process. A Camoufox session owns an isolated page or context selected by its worker.

The engine is immutable for the life of a named session. An omitted mode on an existing session inherits its pinned engine. An explicit `--stealth` request against a standard session returns a clear conflict rather than silently moving state. Claude must choose a new session name to change engines.

The conflict response should name both the session's pinned engine and the newly requested mode. `browser sessions` must expose the same identity, so Claude can inspect an unfamiliar session before submitting engine-specific code.

The browser daemon must distinguish an execution timeout from a dead persistent worker. It can terminate a stuck Browser Use CLI execution or Camoufox code run while retaining a healthy browser session. `stop-all` has exactly one owner and affects only the sessions and processes belonging to the current agent container.

## Container browser lifecycle

Hermes can discover a host Chromium and optionally copy an existing desktop profile. The agent runs inside Docker, so those assumptions do not transfer.

The browser daemon should manage both engines under one lifecycle. Shared requirements are:

* Both browser binaries and their libraries are installed in the immutable image.
* CDP, BiDi, Playwright, and internal worker endpoints bind to loopback or private Unix sockets only.
* Chromium and Camoufox have separate durable profile roots below the agent data directory.
* Health checks verify the endpoint rather than trusting a PID file.
* A dead browser can be restarted without leaving stale session records.
* Browser Use CLI children, Browser Harness workers, Camoufox workers, and browsers are placed in process groups the daemon can clean up.
* Docker's tiny init can reap any child that outlives an unexpected daemon crash.
* Headless automation and headed handover never open the same profile concurrently.
* Engines start on demand. Selecting stealth must not leave an unused Chromium or Camoufox process running indefinitely.

Chromium sessions use the Browser Use and Browser Harness path over CDP. Camoufox sessions use a dedicated process that owns the official in-process AsyncCamoufox and Playwright Firefox objects. The current local [`bidi.py`](../agent/skills/browser/cli/src/vesta_browser/bidi.py) and [`launcher.py`](../agent/skills/browser/cli/src/vesta_browser/launcher.py) are useful migration references because they already solve pinned launches, profiles, fingerprint presets, health, and container behavior. The raw BiDi transport can remain during migration, then be removed after the Playwright worker reaches parity.

The official Camoufox remote server is experimental, and its server form is a poor basis for persistent profiles. Prefer an in-process Camoufox worker launched and supervised by the browser daemon. The worker can create fresh Python execution globals for each request while preserving its browser context. See the [official remote-server warning](https://camoufox.com/python/remote-server/) and [official Python usage](https://camoufox.com/python/usage/).

The Hermes `local` option for copying a real host profile should not be exposed. Supporting it would require a sensitive host mount or a new host service and would weaken per-container isolation.

## Immutable packaging

The image should contain pinned compatible versions of:

* Browser Use, currently reviewed at `0.13.10`.
* Browser Harness, currently pinned by Browser Use at `0.1.13`.
* Chromium and its required system libraries.
* A pinned Camoufox build for each supported architecture, with its hash and Firefox libraries.
* Xvfb, Openbox, x11vnc, and noVNC for handover.

Versions and hashes belong in the repository's dependency lock and image build. Production browsing must not use an unpinned `uvx` invocation or download a browser on first use. Browser telemetry should be disabled in the execution environment.

Use separate locked executor environments behind the daemon:

* Standard environment: Browser Use CLI, Browser Harness, and their CDP dependencies.
* Stealth environment: Camoufox, its compatible Playwright release, and fingerprint dependencies.

Camoufox currently constrains Playwright and relies on Playwright internals, so isolating the interpreters prevents an upgrade for one engine from silently breaking the other. The daemon itself should have a small dependency set and spawn the interpreter belonging to the selected engine. Both environments are created during the image build, never during a browser task. See Camoufox's [package metadata](https://github.com/daijro/camoufox/blob/main/pythonlib/pyproject.toml).

This makes `browser doctor` meaningful immediately after container boot. Setup registers `browser daemon start` with the restart skill so the normal daemon is already available, while its start command remains safe to repeat.

## User handover

Handover is a browser-daemon operation because the daemon owns both browsers and their profiles. The handover request selects the same named session and engine that automation will resume.

The flow should be:

1. Resolve the session to Chromium or Camoufox and reserve that engine's profile.
2. Stop or detach its headless browser cleanly.
3. Start the same engine headed on a private Xvfb display, with CDP for Chromium or its Firefox control endpoint for Camoufox.
4. Start Openbox, x11vnc, and noVNC.
5. Register the `browser` service with vestad without `--public`.
6. Return only after health checks make `context.handover.state` equal `live`. Include the service name, `handover.html` path, handover id, session, engine, expiry, and private-service state. Do not mint or return a public URL inside the daemon.
7. Claude mints a service-scoped key with a TTL no longer than the handover lifetime.
8. Claude builds the path-keyed URL and sends that URL to the user.
9. While the user is connected, report `control_owner: handover_user` and reject agent actions against that session with `handover_in_use`. Do not let the user and Claude race to control the same page.
10. On completion, Claude stops handover and revokes the minted key. The daemon unregisters the route on stop, expiry, failure, or shutdown.
11. Stop the headed process, resume the same engine headless with the same profile, refresh page metadata, and return `control_owner: agent`. A later explicit browser call may capture or inspect the post-login page.

The instruction in `SKILL.md` should use this shape, substituting the unique label and TTL returned by `browser handover start`:

```bash
browser handover start --url "https://example.com/sign-in"
KEY=$(service-key mint browser --label "browser-handover-<id>" --ttl 1800)
echo "$VESTAD_PUBLIC_URL/agents/$AGENT_NAME/browser/k/$KEY/handover.html"
```

For a Camoufox login, the first command also supplies `--session <name> --stealth`. Later automation reuses that session name, so it resumes the same Camoufox profile rather than the unrelated Chromium profile.

The `/k/<key>/` path form is deliberate. Relative noVNC assets and WebSocket paths inherit the credential prefix, unlike an authorization header that a normal browser link cannot set. The service key is scoped to `browser`; it cannot open another private service.

After the user finishes:

```bash
browser handover stop
service-key list browser
service-key revoke browser <id>
```

`service-key mint` returns the secret only once. The unique label lets Claude identify the corresponding key id in `service-key list browser` before revoking it. Expiry is a backstop, not a substitute for revocation after a completed handover.

`browser handover status` must return the standard result envelope and make these facts distinct:

* `state: live` means the headed engine, X display, VNC bridge, web bridge, and private vestad route all passed their health checks.
* `live` does not mean that a service key exists or that a link has been sent.
* `private_service: registered_private` confirms that the route is registered without `--public`.
* `user_access: active` means vestad reports a live service key whose label matches `browser-handover-<id>`. Status includes its key id and expiry but never its secret.
* `viewer_connected: true` means a user currently has a live handover WebSocket, and `control_owner` must then be `handover_user`.
* `expires_at` is the hard handover deadline. Status must not describe an expired or unhealthy runtime as live.

On each status request, the daemon should obtain current service registration and matching key metadata through vestad's self-scoped API. Vestad remains the owner of service keys. The browser daemon merely joins that read-only fact to its own handover health. If vestad cannot be reached, status reports `user_access: unknown` rather than guessing from cached data.

The daemon must not capture the screen automatically while the user controls a handover because it may contain credentials or other sensitive input. It may refresh URL, title, tab, and health metadata. Any earlier screenshot becomes `stale`; after handover stops, Claude must deliberately request and read a new screenshot before making a visual claim.

The existing [`service-key`](../agent/skills/vestad/scripts/service-key) helper, the [private-service convention](../agent/skills/vestad/SKILL.md), and [`ServiceKeyStore`](../vestad/src/service_keys.rs) provide the gateway primitive. A handover needs a hard maximum lifetime and inactivity timeout. A dead handover must not leave a public route, and the short key TTL limits a credential Claude fails to revoke.

Camoufox and Chromium profiles remain separate. A compatible current Camoufox profile can be preserved for the stealth engine, subject to the pinned-version migration check. It cannot become a Chromium profile. A login created in one engine is not automatically present in the other; use handover for the engine that needs the authenticated session. Cookie conversion or silent synchronization should not be attempted.

## Existing skill compatibility

This architecture fits existing internal callers better than a native-only tool:

* [`maps/browser_bridge.py`](../agent/skills/maps/cli/src/gmaps_cli/browser_bridge.py) already shells out to `browser` for authenticated Google Maps requests.
* [`microsoft/capture.py`](../agent/skills/microsoft/cli/src/microsoft_cli/capture.py) already uses browser sessions, handover, navigation, evaluation, snapshots, and cleanup.
* [`agent/MEMORY.md`](../agent/MEMORY.md), Maps instructions, and Flights instructions already reference the browser skill and CLI.

During migration, required legacy commands can translate into daemon RPCs. The end state should move Maps and Microsoft to either `browser exec` or a small typed browser-daemon client library. They must not invoke Browser Use CLI or connect directly to Chromium or Camoufox because doing so would bypass daemon policy and session ownership.

## Security boundary

`browser exec` runs model-written Python. It remains a powerful execution surface, not a sandbox. Claude already has Bash under `bypassPermissions`, so the new CLI does not introduce an entirely new authority class. The daemon still provides a valuable common enforcement point.

Required controls are:

* A mode-`0600` Unix socket located in an agent-private directory.
* Versioned requests with bounded fields and payloads.
* Daemon-owned workspace containment.
* Minimal child environments with unrelated secrets removed.
* Backend-specific credential injection only when required.
* Loopback-only CDP, Playwright transport, VNC, and websockify listeners.
* Scoped and expiring vestad service keys for handover.
* Bounded and redacted output.
* Process-group termination on timeout and shutdown.
* Logs that exclude source code, page bodies, cookies, authorization headers, credentials, and service keys.

If model-written browser code must later be treated as hostile, the execution child needs a separate sandbox with its own filesystem and network policy. That is a distinct security project, not part of copying Hermes' present browser behavior.

## Observability and recovery

`browser doctor` and `browser daemon status` should report daemon-owned facts:

* Browser Use and Browser Harness versions.
* Chromium version and executable path.
* Camoufox package, browser version, executable path, and fingerprint profile identity.
* Daemon PID, protocol version, and socket health.
* Chromium CDP and Camoufox worker health.
* Logical sessions, resolved engines, worker health, and last activity.
* Selected mode, engine, backend, protocol, portable API version, and engine extensions without credential values.
* The complete standard and stealth routing table returned by `browser engines`.
* Workspace root, retention, and disk usage.
* Handover lifecycle, private-service health, matching service-key state, viewer connection, control owner, and current expiry.
* The final page identity and whether its visual observation is current, stale, or absent.
* Last launch, execution, timeout, cancellation, and cleanup error.

The daemon should emit structured lifecycle events for request start, backend selection, completion, timeout, cancellation, worker restart, browser restart, and handover transitions.

`browser daemon restart` should not replace a live but unhealthy daemon without first applying the standard bounded shutdown path. Stale sockets and PID files are removed only after liveness checks. Ordinary `browser exec` calls never own daemon startup or restart.

## What is retired

After rollout, remove:

* The first-use Camoufox downloader, replaced by immutable pinned packaging.
* The raw WebDriver BiDi implementation after the Camoufox Playwright worker reaches parity.
* The custom CDP compatibility translator.
* The current Camoufox daemon and its protocol.
* Semantic DOM reference ids such as `@e12` from the primary browser interface.
* The old model-facing action commands such as `browser click`, `browser type`, and `browser wait`.
* Public handover service registration.
* Runtime browser downloads.

Keep:

* The browser skill directory and activation mechanism.
* A rewritten `SKILL.md` and `SETUP.md`.
* The `browser` executable name.
* The new thin CLI client and browser daemon implementation.
* The pinned Camoufox engine, fingerprint configuration, and supervised Playwright worker.
* Handover assets and display dependencies shared by Chromium and Camoufox.
* Required third-party notices and attribution history.

The domain recipe library may remain as optional skill references. It must not obscure the main `browser exec` contract or cause every browser task to load a large prompt.

## Proposed repository ownership

| Concern | Proposed owner |
|---|---|
| Model-facing instructions | `agent/skills/browser/SKILL.md` |
| Operational setup and recovery | `agent/skills/browser/SETUP.md` |
| Thin CLI and RPC client | rewritten browser CLI package |
| Daemon lifecycle commands | `browser daemon start|stop|restart|status` in the browser CLI |
| Internal foreground server | `browser serve`, launched only by `browser daemon start` |
| Versioned RPC server | browser skill runtime daemon package |
| Validation and execution environment | browser daemon |
| Mode, engine, backend, and provider registry | browser daemon |
| Workspaces and artifacts | browser daemon |
| Standard executor and Browser Harness workers | browser daemon using upstream Browser Use |
| Stealth executor and Camoufox workers | browser daemon using official AsyncCamoufox and Playwright |
| Chromium, Camoufox, and profile lifecycle | browser daemon |
| Handover process orchestration | browser daemon |
| Private handover access | existing vestad proxy and service-key store |
| Immutable dependencies | `vestad/Dockerfile` and the agent dependency lock |
| Skill activation | existing `VestaConfig.active_skills` and boot symlink farm |

No browser-specific implementation belongs in `agent/core/tools.py`, `agent/core/client.py`, or `agent/core/cc_sdk/`.

## Migration plan

### Phase 0: freeze contracts

* Pin Browser Use, Browser Harness, Camoufox, and the helper digest.
* Record licenses and attribution requirements.
* Define the daemon RPC, CLI syntax, structured result, and artifact contract.
* Define standard and stealth modes, engine pinning, backend configuration, and secret names.
* Define the engine vocabulary, per-engine capability manifests, result envelope, closed state enums, observation freshness rules, and error codes Claude will see.
* Keep a temporary legacy runtime switch for rollback.

### Phase 1: build the browser daemon

* Implement the protected socket, singleton startup lock, protocol version, and health operations.
* Put validation, mode and backend routing, workspaces, screenshots, sessions, timeouts, and cleanup in the daemon.
* Make every RPC return the common context envelope and refresh verified page state after execution.
* Add Chromium, Camoufox, and their pinned dependencies to the image.
* Supervise Browser Use CLI children, Browser Harness workers, Camoufox Playwright workers, and both browser engines.
* Leave the current model-facing path enabled while the daemon is incomplete.

### Phase 2: replace the CLI internals

* Rewrite `browser exec` as a thin daemon client.
* Add `--stealth` as an explicit capability request and report the resolved engine in every result.
* Add doctor, status, session cleanup, and cancellation RPC clients.
* Add temporary translations for Maps and Microsoft commands.
* Ensure no CLI command imports or starts an independent browser driver.

### Phase 3: rebuild handover

* Move handover orchestration into the browser daemon.
* Support headed Chromium and headed Camoufox, each using its own automation profile.
* Replace public registration with a scoped, expiring service key.
* Report runtime liveness, private registration, matching key state, viewer presence, and control ownership as separate facts.
* Prevent browser execution from racing a connected handover user, then verify that the matching executor resumes the session after handover stops.

### Phase 4: rewrite the skill surface

* Replace the current action guide with the concise `browser exec` contract and helper digest.
* State prominently that Chromium and Camoufox are different engines, then document standard mode as the default, the evidence threshold for stealth, the portable helper subset, and engine-specific escape hatches.
* Teach Claude to use `browser engines`, inspect engine fields in results and sessions, and treat `engine_capability_mismatch` as a request to change code or deliberately start a new session rather than as permission to retry automatically.
* Teach Claude the fixed result-reading order and the difference between page metadata, a captured screenshot, and an image the model has actually read.
* Update `SETUP.md`, Maps, Microsoft, Flights, and memory references.
* Teach the explicit screenshot path plus file-read step.
* Make the new daemon path the default while retaining rollback for one release window.

### Phase 5: delete the legacy control paths

* Remove the old per-session daemon, CDP translator, semantic refs, and old action execution.
* Remove raw BiDi after the supervised Camoufox Playwright executor meets the required parity. Keep Camoufox itself.
* Remove obsolete packages and runtime download code.
* Remove the rollback switch after the release window.
* Remove compatibility commands once direct callers use the stable daemon client.

## Acceptance criteria

The replacement is complete only when:

### Skill interface

* Claude can discover the browser through the ordinary skill mechanism.
* No native `browser_exec` tool is registered through the Claude Agent SDK.
* `SKILL.md` is sufficient to execute a multi-step browser program through Bash.
* The normal-use instructions follow the fixed order: choose mode, run code, use shared helpers, inspect results, then consult advanced sections only when needed.
* Shared helpers are taught once rather than through duplicate Chromium and Camoufox examples.
* Daemon internals, provider routing, dependencies, and socket details stay out of the normal-use path.
* `SKILL.md` explicitly teaches that Chromium and Camoufox are separate engines with different protocols, profiles, and engine-specific APIs.
* `browser engines` exposes the active mode-to-engine mapping and a versioned capability manifest in machine-readable form.
* `SETUP.md` completely documents runtime and recovery requirements.
* The CLI is only an RPC client and contains no backend or browser logic.

### Daemon ownership

* The browser daemon is the sole owner of validation, routing, workspaces, screenshots, sessions, execution children, Browser Harness workers, Camoufox workers, both browser engines, and handover.
* Every consumer uses the same versioned daemon protocol.
* Every command returns the same top-level result envelope with explicit states instead of meaning encoded by absent fields.
* No skill CLI connects directly to Chromium or Camoufox, and none invokes Browser Use independently.
* Timeout, cancellation, shutdown, and daemon restart leave no uncontrolled execution child.
* Browser and worker health remain diagnosable after a failed call.

### Behavior

* One `browser exec` call can perform a multi-step browse and extraction.
* Standard mode exposes the full pinned Browser Use CLI 3.0 execution surface.
* `browser exec --stealth` selects the managed Camoufox executor and exposes the documented portable helper surface.
* Named sessions preserve browser state while Python variables reset between calls.
* Parallel sessions do not accidentally operate on the same tab.
* A session remains pinned to its initial engine, and an explicit conflict fails rather than switching silently.
* Every engine-bound success and failure reports mode, engine, backend, protocol, portable API version, and engine extensions.
* A recognized engine-specific operation used on the wrong engine returns `engine_capability_mismatch` with an actionable alternative and never silently falls back.
* `browser sessions` makes each live session's pinned engine visible before Claude reuses it.
* Every execution reports its closed execution state and a fresh final page observation, or explicitly reports that the page is unavailable.
* Active and completed executions expose a safe current or last action marker without recording source code, page content, credentials, or typed values.
* Visual state is `current`, `stale`, or `absent`, and a screenshot path is never described as an image Claude has already seen.
* Every error identifies its phase, retryability, and suggested action while preserving verified session, page, and handover context.
* A failed standard request is never automatically replayed in stealth mode.
* New tasks receive new daemon workspaces, and explicit reuse works across follow-up calls.
* Screenshot results from either engine contain safe paths that Claude can read visually in the next tool step.
* A fresh image can use either engine without downloading an executable at runtime.

### Vesta integration

* Authenticated Google Maps page calls still work.
* Microsoft SSO, user handover, and post-login capture still work.
* Handover can target either a standard or stealth session and resumes the same engine and profile.
* Handover registers `browser` privately and never uses `--public`.
* Claude mints a browser-scoped service key and shares the `/browser/k/<key>/handover.html` path.
* Every handover key expires, can be identified by its unique label, and is revoked after use.
* `browser handover status` distinguishes runtime liveness, private registration, user-access key state, viewer connection, control ownership, and expiry.
* A connected handover user and Claude can never control the same session concurrently.
* Agent restart, container rebuild, and notification behavior keep their existing owners.
* No change imports, modifies, or enables dormant `cc_sdk`.

### Retirement

* Camoufox remains supported after the old Camoufox daemon and action surface are removed.
* Raw BiDi is removable only after the official Playwright-based Camoufox worker meets the accepted stealth behavior.
* The compatibility commands contain no independent browser engine.
* Only the new daemon controls Chromium, Camoufox, their workers, and their profiles.

## Consequences and accepted tradeoffs

This decision has clear benefits:

* It matches the way other Vesta capabilities are taught and invoked.
* Browser logic has one owner that can serve Claude and internal skill CLIs.
* The agent core remains browser-agnostic.
* The daemon can centralize security, health, cleanup, and provider behavior.
* Browser Use and Browser Harness upgrades remain contained within one subsystem.

It also accepts these costs:

* The model call is generic Bash rather than a typed native browser tool.
* Tool input validation happens after Bash starts, inside the browser daemon.
* Screenshots require a second file-read step when Claude needs to see them.
* The daemon cannot infer the active turn id, so workspace continuity is explicit in the CLI contract.
* A long browser command remains a foreground Bash step and can delay urgent notification delivery until that step finishes.
* Two engines increase packaging, health-check, session, and handover complexity.
* Full raw Browser Harness and CDP behavior is available only in standard mode. Stealth mode guarantees the documented portable helper surface plus its Playwright escape hatch.
* Chromium and Camoufox keep separate profiles, so a login or cookie created in one does not appear in the other.
* Model-written Python remains powerful and is not sandboxed merely because a daemon executes it.

These are deliberate consequences of choosing the standard Vesta skill interface over Hermes' native tool boundary.

## Final recommendation

Build one per-agent browser harness daemon and make it the exclusive owner of all browser behavior. Keep `SKILL.md`, `SETUP.md`, and the `browser` CLI as the interface Claude understands. Make that CLI a minimal RPC client with standard mode by default and an explicit `--stealth` request.

Copy Hermes' compact helper guidance, code execution model, validation, environment hygiene, backend routing, named sessions, workspace behavior, timeout handling, and artifact discovery into the browser daemon. Keep the full Browser Use CLI and upstream Browser Harness path for Chromium. Add a separately supervised Camoufox Playwright executor for stealth, sharing the daemon's policy, workspace, artifact, lifecycle, and handover layers.

Do not add a native Claude Agent SDK browser tool. Do not let this decision create parallel CLI and native paths. Every browser caller should converge on the daemon behind the single `browser` command.

## Primary sources

* [Hermes browser documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/browser)
* [Hermes `browser_exec` adapter](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/tools/browser_use_cli.py)
* [Hermes model tool registration](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/model_tools.py)
* [Hermes browser provider registry](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/agent/browser_registry.py)
* [Browser Use CLI implementation](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/browser_use/cli.py)
* [Browser Use package metadata](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/pyproject.toml)
* [Browser Use skill](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/skills/browser-use/SKILL.md)
* [Browser Harness repository](https://github.com/browser-use/browser-harness)
* [Browser Harness execution entry point](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/run.py)
* [Browser Harness daemon](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/daemon.py)
* [Browser Harness helper API](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/helpers.py)
* [Camoufox repository](https://github.com/daijro/camoufox)
* [Camoufox Python and Playwright usage](https://camoufox.com/python/usage/)
* [Camoufox remote-server documentation and warning](https://camoufox.com/python/remote-server/)

No live browser runs or test suites were used to produce this architecture report. It is based on static source review of the pinned revisions above and the local repository at the stated revision.
