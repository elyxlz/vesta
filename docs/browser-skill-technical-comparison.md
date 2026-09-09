# Browser Skill Technical Audit: Hermes and Browser Use CLI 3.0

Status: technical companion to the [functional overview](./browser-agent-functional-overview.md)  
Review date: 2026-09-04  
Local revision: `a5c52c560dcf504fcd6226239d160c8434e70c63`  
Hermes revision: [`6327930`](https://github.com/NousResearch/hermes-agent/tree/63279301bcbdc185c1b07b98a9312eb0c862f26d)  
Browser Harness revision: [`10b2086`](https://github.com/browser-use/browser-harness/tree/10b2086c29f0696a6712956d2914e03012f5ebd0)  
Browser Use revision: [`fe5ad35`](https://github.com/browser-use/browser-use/tree/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a)

## Decision summary

The current browser skill should not be replaced wholesale with Browser Use CLI 3.0. It already implements the same fundamental execution pattern: short-lived model-written Python calls, pre-imported browser helpers, and a named daemon that preserves the browser connection. Its recipe library was also originally imported from Browser Harness.

The largest difference is below and above that executor:

- Below it, the current skill drives a pinned Camoufox browser over raw WebDriver BiDi. Browser Use CLI delegates to Browser Harness, which drives Chromium-family browsers over raw CDP.
- Above it, the current agent harness gives Claude an on-demand skill and Bash. Hermes gives its model one native `browser_exec` tool and supervises sessions, workspaces, browser routing, timeouts, permissions, and screenshots inside the harness.

The recommended direction is:

1. Fix the current handover, recipe-routing, wait, screenshot, feedback, and remote-session defects.
2. Experiment with a native structured wrapper over the existing Camoufox executor.
3. Add Browser Harness only as an optional CDP backend if Chrome, Lightpanda, or cloud browsers are required.
4. Compare the interface and engine choices independently before changing defaults.

## Scope and terminology

This is a static source audit. It covers the model-facing interface, process topology, browser driver, state, perception, action model, backend routing, safety boundary, and test posture. It does not reproduce Hermes' internal benchmark or run either external project against a live browser.

Four terms need to stay distinct:

- **Browser skill**: the local implementation under [`agent/skills/browser/`](../agent/skills/browser/).
- **Browser Harness**: the thin CDP and Python execution package at [`browser-use/browser-harness`](https://github.com/browser-use/browser-harness).
- **Browser Use CLI 3.0**: the current Browser Use CLI generation. At the reviewed revision, its stdin path delegates to Browser Harness. Browser Use itself reports package version `0.13.10` and pins `browser-harness==0.1.13`, so `3.0` is not the Python package major version. See its [`CLI`](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/browser_use/cli.py) and [`package metadata`](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/pyproject.toml).
- **Hermes adapter**: the native tool and lifecycle code in Hermes' [`tools/browser_use_cli.py`](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/tools/browser_use_cli.py).

## Current browser skill: technical design

### Lineage and activation

The browser skill is a default active skill through [`agent/core/default-skills.txt`](../agent/core/default-skills.txt). During boot, [`reconcile_claude_runtime`](../agent/core/claude_runtime.py) merges configured and default skills, then rebuilds the symlinks that Claude Agent SDK discovers under `~/.claude/skills`.

Git history records two useful milestones:

- 2026-04-23, commit `6cc15d208`: the Python CLI, raw CDP, and Browser Harness skill library were imported.
- 2026-07-09, commit `11148a0d0`: the local browser engine changed to Camoufox over raw BiDi.

[`ATTRIBUTION.md`](../agent/skills/browser/ATTRIBUTION.md) confirms that the domain and interaction recipes were initially imported from Browser Harness. The current system is therefore a Browser Harness descendant at the instruction and executor level, with a later independent driver.

### Process topology

```text
Claude through Bash
       |
       v
short-lived `browser` CLI
       |
       | JSON over per-session Unix socket
       v
long-lived browser daemon
       |
       | native BiDi or translated CDP
       v
owned Camoufox or attached Chrome
```

The CLI supports both action subcommands and full Python stdin. [`cmd_stdin`](../agent/skills/browser/cli/src/vesta_browser/cli.py) starts the daemon, imports every public helper, reads the code, and calls `exec`.

The daemon in [`daemon.py`](../agent/skills/browser/cli/src/vesta_browser/daemon.py) is keyed by `BROWSER_SESSION`. It owns:

- The browser WebSocket connection.
- The current browsing context.
- A 500-event ring buffer.
- Current native-dialog state.
- Context recovery when the selected tab closes or becomes stale.

The Python interpreter is fresh for each CLI call. Browser state persists because the daemon and browser remain alive.

### Browser and protocol

[`launcher.py`](../agent/skills/browser/cli/src/vesta_browser/launcher.py) pins Camoufox tag `v150.0.2-beta.25`, along with architecture-specific filenames and SHA-256 digests. It downloads, verifies, and caches the browser on first launch.

Ordinary launches are headless. The browser is driven with raw WebDriver BiDi through [`bidi.py`](../agent/skills/browser/cli/src/vesta_browser/bidi.py). An external Chromium browser can be attached through [`cdp_backend.py`](../agent/skills/browser/cli/src/vesta_browser/cdp_backend.py), which adapts the daemon's BiDi-shaped requests to CDP.

The declared Python runtime dependency is only `websockets>=15`. Camoufox and its Linux shared libraries are separate runtime artifacts. This is materially smaller than introducing the full Browser Use distribution and Browser Harness dependency tree.

### Profiles and fingerprints

The local browser supports:

- A shared profile under `~/.browser/profile`.
- Ephemeral session profiles under `~/.browser/ephemeral`.
- Explicit durable profiles through `--user-data-dir`.

Three bundled fingerprint presets are selected deterministically from the profile path. One profile keeps a coherent fingerprint across restarts, while separate profiles can receive different fingerprints.

This makes browser identity and authentication state profile-scoped. `BROWSER_SESSION` alone isolates the daemon and current tab, not the profile.

### Perception and refs

The local BiDi path does not expose a native browser accessibility tree. [`snapshot.py`](../agent/skills/browser/cli/src/vesta_browser/snapshot.py) injects a vendored `dom-accessibility-api` based walker into the page. It:

1. Walks the DOM.
2. Computes roles and accessible names.
3. Produces a compact indented semantic view.
4. Assigns refs such as `e1` to interactive elements.
5. Stores the ref map in `window.__vestaRefs`.

This is token-efficient and ergonomic, but it is a DOM-derived projection rather than the browser's native accessibility tree. A parent page cannot inspect a cross-origin iframe this way. Canvas content and closed shadow roots also require a screenshot, coordinates, or a different browsing context.

Refs are snapshot-local. A new snapshot overwrites the map, and navigation replaces the page realm.

### Actions

Ref clicks resolve an element's viewport center and inspect `document.elementFromPoint`. If an overlay covers the target, the command returns a nonzero exit and describes the element that received the click. The actual input uses BiDi `input.performActions`, which produces trusted pointer input.

Ref typing focuses the element and sends real keyboard input. It appends by default and does not clear the existing value. Browser Harness' `fill_input` is stronger for framework-controlled fields because it selects all, clears, types with key events, and emits input and change events.

The local helpers also cover raw BiDi, JavaScript, coordinates, tabs, screenshots, PDF output, native dialogs, file upload, HTTP requests, browser events, and waits.

### Navigation and readiness

Normal navigation asks BiDi to wait for `complete`, then the CLI additionally polls `document.readyState == "complete"` for up to 15 seconds.

The accepted wait state `networkidle` is currently misleading. Both `browser wait --load-state networkidle` and `browser wait --load-state load` call the same ready-state poll. Browser Harness has a true CDP Network-event implementation, which is a useful behavior to port or reproduce with BiDi network events.

Navigation initiation and task readiness should be separate concepts. A rendered SPA may be usable well before the full load event, while `document.readyState == "complete"` does not prove its application data is ready.

### Output and feedback

Sessions can use accessibility, screenshot, or combined perception. Navigation, click, type, press, and focus normally print new feedback. The skill guide says every action returns an updated view, but `hover`, `scroll`, `close`, and `resize` currently do not.

Recipe hints are added only by the snapshot formatter. Screenshot-only feedback can therefore hide a recipe that the same URL would surface in accessibility mode.

The screenshot helper advertises PNG, JPEG, and WebP. BiDi supports PNG and JPEG in this implementation, so WebP requests are sent as JPEG while the output path keeps a `.webp` suffix. That creates JPEG bytes with a WebP filename.

Python stdin can print unbounded output. There is no structured result envelope or automatic artifact fallback for large results.

### Domain and interaction recipes

The local corpus has 77 domain recipe files and 13 interaction guides. Automatic recipe discovery checks:

1. A directory named after the exact hostname.
2. For deeper hostnames, a directory named after the final two labels.
3. `hosts:` frontmatter inside every recipe.

The recipe directories instead use product slugs such as `amazon`, `github`, and `booking-com`. Only four of the 77 files declare `hosts:` frontmatter. The automatic URL banner therefore reaches only those four files under normal public URLs. The other 73 remain available only if Claude manually lists or searches the corpus.

Current Browser Harness maps the first hostname label to its slug directory. That works for many domains but remains a heuristic. An explicit host-pattern index would be more reliable for both corpora.

### Remote attachment

`browser connect` handles HTTP discovery, raw CDP WebSockets, and BiDi WebSockets ending in `/session`. Two implementation gaps affect remote sessions:

- HTTPS discovery is rewritten to `ws://`, not `wss://`.
- Session enumeration starts from browser PID files. A remote attachment has endpoint and daemon records but no owned browser PID, so it can be absent from `browser sessions` and `browser stop-all`.

The lifecycle model should distinguish an owned browser process from an attached endpoint while still enumerating both.

### Handover

[`handover.py`](../agent/skills/browser/cli/src/vesta_browser/handover.py) starts a headed Camoufox on Xvfb, adds Openbox, exposes the display through x11vnc and websockify, and serves a branded noVNC page. It normally reuses the shared profile so the user's login persists into later automation.

The exposure boundary is currently unsafe for an interactive authenticated browser:

- It registers `browser` with `--public`.
- [`vestad/src/auth.rs`](../vestad/src/auth.rs) accepts a public service without a credential.
- x11vnc is started with `-nopw` and listens behind the local proxy bridge.
- The returned URL contains no scoped service key.
- No maximum lifetime or inactivity expiry exists.
- Deregistration on stop is best effort.

Anyone who can reach and obtain or guess the route can attempt to control the browser while the handover is active. The route path is a locator, not an authentication boundary.

### Test posture

The local browser CLI contains 248 statically counted test functions across ten test modules. They exercise CLI, admin, daemon, BiDi, CDP translation, helpers, launcher, presets, snapshots, and handover behavior with fakes and mocks.

No live Camoufox browser smoke test was found in this focused suite. The tests protect local logic, but not the full launch, navigation, snapshot, action, and shutdown seam in the production container.

## Hermes: technical integration

### Tool-surface selection

Hermes defaults to Browser Use mode when `browser.backend` is unset and either `browser-use` or `uvx` is runnable. An explicit `browser.backend: browser-use` forces it. `browser.backend: off` or `/browser use off` selects Hermes' built-in browser tools. If the CLI is unavailable under the default setting, Hermes falls back and emits a rate-limited notice. Camofox also forces the built-in path because Browser Harness requires CDP. See the [Hermes browser guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/browser) and the pinned [adapter](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/tools/browser_use_cli.py).

In Browser Use mode, the model receives one native tool:

```json
{
  "code": "required Python source",
  "session": "optional named session",
  "timeout_s": 300,
  "local": "present only after real-profile consent"
}
```

Hermes removes `browser_exec` from any session whose resolved tool surface lacks terminal access. This is enforced per session in [`model_tools.py`](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/model_tools.py), because the code is arbitrary host Python rather than a constrained browser language.

### Prompt ownership

Hermes does not load Browser Use's full installable `SKILL.md`. Its tool schema contains a Hermes-authored policy and a concise pinned digest of Browser Harness helper names.

The adapter comments say a live `browser-use skill` fetch was removed to avoid uncontrolled third-party prompt content, version drift, and supply-chain exposure. This cleanly separates a pinned runtime dependency from locally reviewed model instructions.

The prompt emphasizes:

- Batch a sub-procedure into one call.
- Print only required results.
- Use a persistent workspace for multi-part tasks.
- Put reusable functions in `agent_helpers.py`.
- Use different guidance for native-vision, text-only, and Lightpanda models.

### CLI discovery and installation

Hermes searches for:

1. A managed `$HERMES_HOME/bin/browser-use`.
2. `browser-use` on `PATH`.
3. The standard user tool bin directory.
4. `uvx browser-use` through the same locations.

Its installer finds or bootstraps `uv`, sets `UV_NO_CONFIG=1`, runs `uv tool install browser-use`, and links the executable into the managed bin directory. The managed copy wins on later calls.

Before invoking the CLI, Hermes strips `PYTHONPATH` and `PYTHONHOME`, ensures core system directories remain on `PATH`, and disables anonymized telemetry unless another value is already set.

### Per-call lifecycle

For each `browser_exec` call, Hermes:

1. Rejects empty code.
2. Scans literal HTTP and HTTPS URLs with its existing URL safety policy.
3. Validates the optional session name.
4. Resolves real-profile consent and the browser backend.
5. Creates a stable per-task workspace and exports `BH_AGENT_WORKSPACE`.
6. Exports the session as `BU_NAME`.
7. Adds a one-time own-tab preamble when a named daemon shares a local browser.
8. Runs Browser Use CLI with the Python source on stdin.
9. Returns structured success, exit code, stdout, workspace, session, and bounded stderr.
10. Detects a newly written screenshot and attaches it directly for a native-vision model.

The timeout is clamped between 5 and 1800 seconds. A subprocess timeout does not guarantee that work already delegated to the long-lived daemon has stopped, so the error warns that the daemon may continue and workspace files remain.

### Browser Use and Browser Harness boundary

The current Browser Use CLI imports and delegates its stdin execution to Browser Harness. Browser Harness' [`run.py`](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/run.py) reads Python, ensures a daemon, imports helpers, loads optional task helpers, and executes the code.

The [`daemon`](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/daemon.py) is keyed by `BU_NAME`. It uses a Unix socket on POSIX and authenticated loopback TCP on Windows. It owns the CDP connection, current target and session, up to 500 events, and dialog state.

The [`helpers`](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/helpers.py) expose raw CDP, navigation, page summaries, input filling, coordinate input, screenshots, tabs, waits, JavaScript, uploads, and HTTP calls. Browser-native AX data is available through `Accessibility.getFullAXTree`; the model is told to filter its thousands of nodes in Python before printing.

### Backend routing

Hermes resolves a browser in this order:

1. Existing `BU_CDP_WS` or `BU_CDP_URL` environment override.
2. `/browser connect`, `BROWSER_CDP_URL`, or configured `browser.cdp_url`.
3. A configured cloud-browser provider through existing Hermes session machinery.
4. A Hermes-managed Lightpanda process.
5. Browser Harness local Chromium discovery or Browser Use direct cloud autospawn.

Hermes' provider registry supports Browser Use and Browserbase in its legacy auto-selection order and explicit providers such as Firecrawl. The registry and policy live in [`agent/browser_registry.py`](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/agent/browser_registry.py).

Named provider sessions receive separate browser instances. Named daemons on a shared local browser receive a new initial tab keyed to the daemon PID. This distinguishes daemon isolation, tab isolation, and browser-process isolation.

### Real-profile access

Hermes can copy the active profile from a default Chromium-family browser and launch a managed browser on that snapshot. The optional `local` tool property appears only after configuration consent. A failure in the consented real-profile route fails closed.

This has a different security model from the local browser skill. Handover lets the user authenticate into an agent-owned profile. Profile copying brings existing user cookies and sessions into a Hermes-managed browser. Both approaches require clear consent and lifecycle guarantees.

### Safety boundary

The literal URL scan is defense in depth, not a sandbox. Python can dynamically build URLs, read files, open sockets, import packages, or launch subprocesses. Hermes' terminal-permission gate is the actual capability boundary.

The current stdin executor has the same arbitrary-code property but runs inside the agent container through Bash. A native wrapper must preserve the same permission and containment boundary. It must not expose Python browser execution where terminal execution was intentionally disabled.

### Screenshots and task workspace

Hermes searches stdout for a screenshot path created during the current call. For native-vision models it resizes and compresses the image before embedding it in the tool result. Text-only models receive a prompt that emphasizes DOM and page-summary helpers instead. Lightpanda receives separate guidance because it has no renderer.

Each task gets a stable workspace under `$HERMES_HOME/cache/browser-use/workspace/<task>`. Browser Harness automatically imports `agent_helpers.py` from it. This provides a cleaner extension point than editing installed helper code during a task, and it lets partial extraction survive across calls.

### Domain knowledge and tests

The reviewed Browser Harness tree contains 107 domain recipe files and 18 interaction guides. Domain lookup is opt-in through `BH_DOMAIN_SKILLS=1`. Hermes does not set that variable and its pinned prompt does not direct the model to this corpus, so its Browser Use integration uses the runtime without surfacing the upstream recipe library.

Hermes' focused Browser Use adapter test file has 114 statically counted tests. Another 77 cover real-profile behavior and three cover Browser Use session expiry. These tests are primarily fake-CLI and mocked-backend tests. Browser Harness has 209 statically counted test functions, also focused on unit-level behavior. No Hermes `browser_exec` test was found that launches the installed Browser Use CLI against a real browser.

## Detailed comparison

| Dimension | Current browser skill | Hermes plus Browser Use CLI | Implication |
| --- | --- | --- | --- |
| Model surface | On-demand `SKILL.md`, Bash actions, Python stdin | One native `browser_exec` tool | Hermes has a cleaner typed boundary. Current Python already has the same batching power. |
| Prompt owner | Local skill and recipe corpus | Hermes-owned header and pinned helper digest | Borrow stable local prompt ownership. |
| Execution | Arbitrary Python inside the container through Bash | Arbitrary host Python through a native tool subprocess | Keep permission parity and container containment. |
| Protocol | Native BiDi plus custom CDP compatibility | Raw CDP through Browser Harness | BiDi preserves Camoufox. CDP expands Chromium integrations. |
| Browser | Pinned and verified Camoufox | Local Chromium, explicit CDP, Lightpanda, or cloud | Keep Camoufox default; add only required routes. |
| Anti-detection | Camoufox fingerprint spoofing with stable profile presets | Ordinary Chromium unless a provider supplies stealth | Browser Use is not a like-for-like stealth replacement. |
| Semantic view | Compact DOM-derived refs | Native AX and DOM through model-written Python | Preserve refs, optionally source them from native AX on CDP. |
| Input | Trusted BiDi actions, overlay detection | CDP input and stronger `fill_input` | Port clear-and-fill behavior without losing ref actions. |
| Feedback | Many actions print the next view | Model prints output; screenshots can be attached automatically | Use a structured envelope and direct image attachment. |
| Sessions | Caller sets daemon name; profile is separate | Typed session, own tab, private provider browser | Model all isolation layers explicitly. |
| Persistence | Daemon, context, events, profile | Daemon, provider session, task workspace, optional profile | Add a per-task workspace locally. |
| Backend choice | Model launches Camoufox or explicitly connects | Harness resolves local, remote, Lightpanda, or cloud | An adapter gives a stable model contract across drivers. |
| Recipes | 77 domain files, but routing reaches four | Upstream corpus exists but Hermes does not surface it | Fix the local corpus index. |
| Waits | `networkidle` aliases ready-state complete | Actual CDP network-idle helper exists | Make wait semantics truthful. |
| Screenshots | Filesystem path; WebP name can contain JPEG | Validated path plus bounded multimodal result | Fix encoding and improve delivery. |
| Dependencies | One Python runtime dependency plus pinned browser | Managed Browser Use install plus Browser Harness | Avoid expanding the default image without a use case. |
| Handover | Integrated noVNC path on agent-owned profile | Optional copied real Chromium profile | Secure handover before adding more auth paths. |
| Platform | Linux container | Host workflows for macOS, Windows, and Linux | Do not import cross-platform complexity the container does not need. |
| Test seam | Extensive mocked tests, no live smoke found | Extensive mocked tests, no live adapter smoke found | Both need a small real-browser contract gate. |

## Priority local findings

### P0: Authenticate and expire handover

Register handover as a private service and mint a short-lived key scoped to the exact agent and service. Put that key in the user URL. Make `vestad` own expiry so agent or browser crashes cannot leave an indefinite route. Add a maximum lifetime and inactivity cutoff.

Acceptance should cover missing keys, wrong-service keys, expiry, idle disconnect, agent crash, gateway restart, and explicit stop.

### P0: Repair recipe discovery

Add an explicit manifest from host patterns to recipe directories. Validate that every domain recipe is reachable or explicitly marked manual-only. Parse the manifest once instead of scanning all Markdown frontmatter for each snapshot.

### P1: Make waits accurate

Implement real network-idle tracking or remove that accepted name. Define the allowed in-flight count, quiet window, long-lived request policy, and timeout result. Separate navigation `none`, `interactive`, and `complete` waits from later task-specific readiness checks.

### P1: Normalize action feedback

Make every mutating action return the selected page view, or document the smaller contract. Prefer a structured result containing page info, semantic snapshot, screenshot, recipes, warnings, and action-specific fields. Recipe hints should not disappear in screenshot mode.

### P1: Fix screenshot media types

Either convert to real WebP or expose the lossy option as JPEG and use a `.jpg` path. Validate magic bytes in a focused unit test.

### P1: Correct remote transport and lifecycle

Map HTTPS discovery to WSS. Enumerate attachments from daemon and endpoint records, not only owned browser PID files. Report ownership so shutdown never kills a browser the skill did not launch.

### P1: Add one live browser contract test

Use a deterministic local fixture site and the production container to verify launch, navigation, snapshot, a trusted click, a framework-controlled field, screenshot encoding, and clean shutdown. Keep it small and serial.

### P2: Add task workspace and output bounds

Give each task a stable workspace with auto-imported `agent_helpers.py`. Bound model-visible stdout and stderr. Store large data as artifacts and return truncation metadata plus paths.

### P2: Add clear-and-fill semantics

Keep append-oriented `type_ref` for compatibility, but add a recommended `fill_ref` that focuses, selects all, clears, types through trusted input, dispatches framework events if needed, and verifies the resulting value.

## Recommended target design

```text
                    model-facing contract
             browser skill plus optional browser_exec
                              |
                    structured result envelope
                              |
                      execution adapter
            policy, session, timeout, workspace
                    /                   \
                   /                     \
       Camoufox and BiDi             optional CDP
      local default, handover       Browser Harness
                   \                     /
                    \                   /
          common refs, actions, recipes, artifacts
```

This separates three choices:

- **Interface**: Bash actions, Python stdin, or native `browser_exec`.
- **Driver**: BiDi or CDP.
- **Browser source**: owned Camoufox, attached Chrome, Lightpanda, or cloud browser.

The common layer should own semantic refs, verified actions, recipe lookup, artifacts, and structured results. Driver adapters should own protocol details. Browser-source adapters should own process or provider lifecycle.

## Phased plan

### Phase 0: Repair the current behavior

Address handover authentication and expiry, recipe indexing, wait semantics, feedback consistency, screenshot format, WSS mapping, remote enumeration, output bounds, and the live contract smoke test.

### Phase 1: Native wrapper over Camoufox

Add an experimental `browser_exec` tool that delegates to the existing Python stdin executor. Give it validated sessions, bounded timeout, per-task workspace, structured output, and direct screenshot attachment. Keep the existing CLI for debugging and action-oriented use.

This phase isolates the benefit of Hermes' harness integration without changing browsers.

### Phase 2: Optional Browser Harness backend

Add a pinned Browser Harness CDP driver behind explicit configuration. Depend directly on Browser Harness if its executor is all that is required. Invoke the Browser Use distribution only when its installer, cloud autospawn, or public CLI compatibility is itself a requirement.

Start with an explicit CDP endpoint or deliberately provisioned local Chromium. Add cloud providers and Lightpanda only with defined credential, billing, expiry, and cleanup ownership.

### Phase 3: Evaluate and route by capability

Compare four arms with the same Claude model and tasks:

| Arm | Interface | Engine |
| --- | --- | --- |
| A | Existing action CLI | Camoufox and BiDi |
| B | Existing Python stdin | Camoufox and BiDi |
| C | Native `browser_exec` | Camoufox and BiDi |
| D | Native `browser_exec` | Browser Harness and CDP |

Use tasks covering SPA navigation, forms, cross-origin frames, shadow DOM, uploads, downloads, tabs, parallel sessions, handover, extraction, timeouts, and recovery. Measure success, accuracy, interventions, tool calls, tokens, latency, memory, cleanup, and retained screenshot bytes.

Hermes reports an August 2026 A/B benchmark in source comments: 108 runs across two models and six multi-step tasks. Its short helper header and full upstream skill dump each achieved 36 of 36 successes, with both reported at roughly 60 percent fewer tokens than Hermes' legacy multi-tool browser surface. This supports a concise pinned digest, but it does not compare Browser Harness with this browser skill and was not reproduced for this report.

## Final recommendation

Borrow Hermes' integration discipline before borrowing its browser engine. A native typed boundary, permission parity, task workspace, structured results, screenshot attachment, and complete session isolation can improve the existing Camoufox path directly.

Keep Camoufox and semantic refs as the default local experience. Treat Browser Harness as an optional CDP capability for Chrome-specific and cloud-browser needs. Let a same-model benchmark determine where either driver wins rather than coupling a new tool interface to a new browser backend.

## Primary sources

### Local

- [`agent/skills/browser/SKILL.md`](../agent/skills/browser/SKILL.md)
- [`agent/skills/browser/ATTRIBUTION.md`](../agent/skills/browser/ATTRIBUTION.md)
- [`agent/core/default-skills.txt`](../agent/core/default-skills.txt)
- [`agent/core/claude_runtime.py`](../agent/core/claude_runtime.py)
- [`agent/skills/browser/cli/src/vesta_browser/cli.py`](../agent/skills/browser/cli/src/vesta_browser/cli.py)
- [`agent/skills/browser/cli/src/vesta_browser/daemon.py`](../agent/skills/browser/cli/src/vesta_browser/daemon.py)
- [`agent/skills/browser/cli/src/vesta_browser/helpers.py`](../agent/skills/browser/cli/src/vesta_browser/helpers.py)
- [`agent/skills/browser/cli/src/vesta_browser/snapshot.py`](../agent/skills/browser/cli/src/vesta_browser/snapshot.py)
- [`agent/skills/browser/cli/src/vesta_browser/launcher.py`](../agent/skills/browser/cli/src/vesta_browser/launcher.py)
- [`agent/skills/browser/cli/src/vesta_browser/handover.py`](../agent/skills/browser/cli/src/vesta_browser/handover.py)
- [`vestad/src/auth.rs`](../vestad/src/auth.rs)

### External

- [Hermes browser guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/browser)
- [Hermes Browser Use adapter](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/tools/browser_use_cli.py)
- [Hermes model tool gating](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/model_tools.py)
- [Hermes browser provider registry](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/agent/browser_registry.py)
- [Browser Use CLI](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/browser_use/cli.py)
- [Browser Use package metadata](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/pyproject.toml)
- [Browser Use browser skill](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/skills/browser-use/SKILL.md)
- [Browser Harness repository](https://github.com/browser-use/browser-harness)
- [Browser Harness skill](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/SKILL.md)
- [Browser Harness executor](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/run.py)
- [Browser Harness daemon](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/daemon.py)
- [Browser Harness helpers](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/helpers.py)
