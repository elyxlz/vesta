# Agent and Browser Skill: Functional Overview and Hermes Comparison

Review date: 2026-09-04  
Local revision: `a5c52c560dcf504fcd6226239d160c8434e70c63`  
Hermes revision: [`6327930`](https://github.com/NousResearch/hermes-agent/tree/63279301bcbdc185c1b07b98a9312eb0c862f26d)

## Summary

The browser skill is not a second agent and the agent harness does not directly drive the browser. The relationship is simpler:

1. The harness makes the browser skill available to Claude.
2. Claude decides when browsing is needed and loads the skill instructions.
3. Claude uses Bash to call the skill's `browser` CLI.
4. The CLI talks to a persistent browser daemon, which drives Camoufox.
5. Browser output returns through Bash to Claude.
6. Claude interprets the page, chooses the next action, and eventually answers the user.

Hermes puts more of this relationship inside its harness. Its model sees one native `browser_exec` tool. Hermes validates the call, chooses a browser backend, creates a task workspace, invokes Browser Use CLI, and returns structured output and screenshots. Browser Use CLI then delegates browser execution to Browser Harness.

The core difference is therefore the integration boundary:

- **Current system**: the skill teaches Claude how to use a shell CLI. The browser runtime belongs to the skill.
- **Hermes**: the harness exposes and supervises a native browser tool. Browser Use and Browser Harness provide the browser runtime behind that tool.

## Current functional relationship

```text
User, notification, or scheduled task
                 |
                 v
        agent harness starts a Claude turn
                 |
                 v
       Claude decides browsing is needed
                 |
                 v
        Claude loads the browser skill
                 |
                 v
      Claude calls `browser` through Bash
                 |
                 v
       browser CLI and persistent daemon
                 |
                 v
             Camoufox
                 |
                 v
      snapshot, screenshot, or CLI result
                 |
                 v
       Claude reasons and takes next step
```

### 1. The harness makes the skill available

The browser skill is active by default through [`agent/core/default-skills.txt`](../agent/core/default-skills.txt). During boot, [`reconcile_claude_runtime`](../agent/core/claude_runtime.py) rebuilds the symlinks under `~/.claude/skills`. This is how Claude Agent SDK discovers the browser skill.

At this point the harness has not launched a browser. It has only made the skill's instructions available to Claude.

### 2. Claude chooses and loads the skill

When a task requires navigation, clicking, form entry, screenshots, or browser-based extraction, Claude loads [`agent/skills/browser/SKILL.md`](../agent/skills/browser/SKILL.md).

The skill tells Claude:

- Which commands are available.
- When to use semantic page snapshots or screenshots.
- How browser sessions and profiles behave.
- How to handle tabs, frames, dialogs, uploads, and difficult sites.
- When to use the user handover flow for authentication.
- Where site-specific recipes and reusable interaction guides live.

The skill is therefore the operational contract and playbook. Claude remains the planner.

### 3. Claude calls the browser through Bash

The model has two functional ways to use the browser.

The first is the action-oriented CLI:

```bash
browser launch
browser open "https://example.com"
browser click e5
browser type e3 "hello" --submit
```

This interface is useful for one action at a time. Most actions return an updated semantic snapshot or screenshot so Claude can verify the result before continuing.

The second is Python stdin mode:

```bash
browser <<'PY'
goto("https://example.com")
wait_for_load()
print(page_info())
PY
```

This lets Claude combine navigation, extraction, actions, waits, and data processing into one Bash call. All public browser helpers are pre-imported. Functionally, this is already similar to Browser Use CLI 3.0's model-written Python approach.

### 4. The CLI connects to a persistent browser runtime

Each `browser` command is a short-lived Python process. It sends requests to a long-lived daemon over a local Unix socket. The daemon is keyed by `BROWSER_SESSION` and owns:

- The browser WebSocket connection.
- The currently selected tab or browsing context.
- Recent browser events.
- Current dialog state.

The daemon normally drives a container-owned Camoufox browser over raw WebDriver BiDi. It can also attach to Chrome through a CDP compatibility backend. The implementation is split across the [`CLI`](../agent/skills/browser/cli/src/vesta_browser/cli.py), [`daemon`](../agent/skills/browser/cli/src/vesta_browser/daemon.py), and [`browser helpers`](../agent/skills/browser/cli/src/vesta_browser/helpers.py).

The persistent daemon is what makes a sequence of separate Bash calls behave like one continuous browser session.

### 5. The browser returns a view to Claude

The normal view is a compact semantic snapshot. The skill injects a DOM walker into the page, calculates roles and accessible names, and assigns refs such as `e1` and `e2`. Claude can then say `browser click e2` without inventing a CSS selector.

The browser can instead return a screenshot path, or both a snapshot and screenshot. Coordinates are available for visual controls, canvas content, shadow DOM, and cases where the semantic view is insufficient.

This establishes a repeated loop:

```text
observe page -> choose action -> execute action -> observe new page
```

Claude owns that loop. The harness only carries Claude's Bash tool calls and their results.

### 6. State persists at several levels

Different kinds of state have different lifetimes:

| State | Lifetime |
| --- | --- |
| Python variables in stdin code | One CLI call |
| Semantic refs such as `e5` | Until the next snapshot or navigation |
| Current tab and browser events | Browser daemon session |
| Cookies and login state | Selected browser profile |
| Browser skill instructions and recipes | Repository and active-skill configuration |
| Claude's reasoning about the task | Current agent session and its persisted context |

For parallel work, each task should use a different `BROWSER_SESSION`. A separate browser session does not automatically mean a separate browser profile, so profile choice also matters when login state or isolation is important.

### 7. Authentication can involve the user

If a site requires the user to sign in, the skill can start a headed Camoufox session and expose it through a browser handover page. The user controls the browser temporarily, completes authentication, and the agent can resume with the resulting profile state.

This flow crosses three components:

```text
Claude requests handover
        |
        v
browser skill starts headed browser and noVNC bridge
        |
        v
vestad exposes the handover service to the user
        |
        v
user signs in, then Claude resumes automation
```

The browser skill owns the headed browser and bridge. `vestad` only publishes the service route. The current route is public and non-expiring until explicit stop, so authentication and expiry should be hardened before this flow is expanded.

## Responsibility boundaries

| Component | Functional responsibility |
| --- | --- |
| Vesta | Works on the user's task, decides when to browse, interprets results, and chooses actions. |
| Agent harness | Runs Claude turns, exposes Bash, and makes active skills discoverable. It does not manage browser tabs or page state. |
| Browser `SKILL.md` | Teaches Claude the browser workflow, commands, safety guidance, and recovery patterns. |
| Browser CLI | Converts Claude's commands or Python into browser operations and formats results. |
| Browser daemon | Preserves the live browser connection and tab state across CLI calls. |
| Camoufox | Loads and renders pages and receives trusted mouse and keyboard input. |
| `vestad` | Publishes the interactive handover service when the browser skill asks for it. |

The important architectural property is that almost all browser-specific behavior remains inside `agent/skills/browser/`. Core makes the skill available but does not contain a browser orchestration layer.

## How Hermes connects its agent to Browser Use

```text
User task
    |
    v
Hermes agent loop
    |
    | native call: browser_exec {code, session, timeout_s}
    v
Hermes Browser Use adapter
    |
    | validates, selects backend, creates workspace
    v
browser-use CLI
    |
    | delegates Python stdin execution
    v
Browser Harness daemon
    |
    | raw CDP
    v
local Chrome, remote Chrome, Lightpanda, or cloud browser
```

Hermes' public documentation describes Browser Use as its default browser backend when the CLI is available. The implementation lives in Hermes' [`tools/browser_use_cli.py`](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/tools/browser_use_cli.py), with the user-level behavior documented in the [Hermes browser guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/browser).

### 1. The harness chooses the browser tool surface

When Browser Use mode is active, Hermes gives the model one tool named `browser_exec` instead of its older browser tool set. The tool normally accepts:

- Python `code`.
- An optional named `session`.
- A bounded `timeout_s`.
- An optional `local` choice when the user has enabled real-profile access.

Hermes removes this tool when terminal access is unavailable because the Python is arbitrary code. That policy is enforced by the harness, not Browser Use.

### 2. The harness prepares each call

Before invoking Browser Use CLI, Hermes:

- Validates the code and session name.
- Applies its URL safety check to literal URLs.
- Chooses the browser backend.
- Creates a stable per-task workspace.
- Isolates named sessions from one another.
- Sets a timeout and cleans the child environment.

This means Hermes owns much more of the integration lifecycle than the current agent harness does.

### 3. Browser Use CLI delegates to Browser Harness

At the reviewed revision, Browser Use CLI's Python execution path is backed by Browser Harness. Browser Use package metadata reports version `0.13.10` and pins `browser-harness==0.1.13`. The `3.0` name refers to the CLI generation, not package major version 3. See the pinned [`Browser Use CLI`](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/browser_use/cli.py) and [`package metadata`](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/pyproject.toml).

Browser Harness uses the same broad process pattern as the current browser skill:

- A fresh Python process runs each code block.
- A named daemon preserves the browser connection.
- Helpers are pre-imported.
- The model prints only the information it wants returned.

The main protocol difference is that Browser Harness drives Chromium over CDP, while the current browser skill normally drives Camoufox over BiDi.

### 4. Hermes owns backend selection

The adapter can route Browser Harness to:

- An explicit CDP endpoint.
- The user's local Chromium browser.
- A consented copy of a Chromium profile.
- Lightpanda.
- Browser Use cloud or another configured cloud-browser provider.

Hermes reuses its provider session cache, expiry, and cleanup machinery. A named cloud session receives its own browser; a named session on shared local Chrome receives its own initial tab.

### 5. Hermes returns a structured result

The adapter returns success, exit code, stdout, bounded stderr, workspace, and session information. If the Python prints a newly created screenshot path and the model supports native vision, Hermes attaches the image directly to the tool result.

The stable task workspace also supports `agent_helpers.py`, JSON files, and CSV files that survive between `browser_exec` calls. Python variables remain call-local.

### 6. Hermes uses a local prompt, not the upstream skill

Hermes does not load Browser Use's full installable `SKILL.md` into the agent. It keeps a concise, pinned helper digest inside the `browser_exec` tool description. The source says this avoids third-party prompt drift and supply-chain exposure.

Functionally, Hermes combines:

- A Hermes-owned browser policy and tool contract.
- Browser Use as the installed CLI entry point.
- Browser Harness as the browser execution layer.

## High-level comparison

| Question | Current system | Hermes |
| --- | --- | --- |
| How does the model discover browsing? | Claude loads an active on-disk skill when relevant. | Hermes exposes a native browser tool when Browser Use mode is selected. |
| What does the model call? | Bash commands or Python stdin through `browser`. | `browser_exec` with Python code in a typed tool argument. |
| Who owns browser policy? | Mostly `SKILL.md` and the browser CLI. | Mostly the Hermes adapter and native tool description. |
| Who selects the browser backend? | The model calls launch or connect through the skill. | The Hermes harness resolves local, remote, Lightpanda, or cloud routing. |
| What persists? | Browser daemon, tab state, events, and profile. | Browser daemon, backend session, task workspace, and optional profile state. |
| How is the page represented? | Compact DOM-derived semantic refs, screenshots, or both. | Model-written DOM or CDP inspection, native AX data, and screenshots. |
| How are actions expressed? | Ref actions, coordinates, subcommands, or Python helpers. | Python helpers and raw CDP, commonly using selectors or coordinates. |
| How are results returned? | Bash stdout, stderr, and screenshot paths. | Structured native tool result with optional attached screenshot. |
| Main local browser | Pinned Camoufox over BiDi. | Chromium-family browser over CDP. |
| Where does isolation happen? | Caller chooses `BROWSER_SESSION` and profile. | Tool schema, adapter, daemon name, tab ownership, and provider session. |
| Does the harness understand browser state? | No. Browser state stays within the skill runtime. | Yes. The adapter understands sessions, backends, workspace, and result media. |

## What this means for improving the browser skill

The useful Hermes idea is not simply replacing Camoufox with Browser Use. The current browser skill already has model-written Python, pre-imported helpers, and a persistent daemon. The useful change is to improve the connection between the agent harness and that runtime.

A practical direction is:

1. Keep the browser skill as the source of browsing instructions, recipes, and recovery guidance.
2. Keep Camoufox and BiDi as the default local engine for its reproducibility and anti-detection properties.
3. Experiment with one native `browser_exec` wrapper that delegates to the existing browser CLI. This would give the harness typed sessions, bounded timeouts, structured errors, task workspaces, and direct screenshot attachments.
4. Keep the existing Bash commands for debugging and precise one-step actions.
5. Add Browser Harness only as an optional CDP backend if local Chrome, Lightpanda, or cloud-browser support is required.
6. Keep one model-facing browser contract regardless of engine, so Claude does not need separate browsing languages for BiDi and CDP.

This separates two independent choices:

```text
How Claude calls the browser: Bash skill or native browser_exec

Which browser is underneath: Camoufox/BiDi or Chromium/CDP
```

They should be evaluated independently. A native tool may improve reliability and result handling without changing browsers. A CDP backend may expand browser coverage without replacing the skill's semantic refs and accumulated recipes.

## Bottom line

Today, the agent harness provides the browser skill to Claude, then gets out of the way. Claude reads the skill, calls its CLI through Bash, and drives a persistent Camoufox session by repeatedly interpreting snapshots and issuing actions.

Hermes moves the adapter one layer upward. Its harness gives the model a single native tool, supervises each execution, chooses the browser source, manages workspace and isolation, and packages the result. Browser Use CLI and Browser Harness handle the browser connection underneath.

The best improvement path is to borrow that structured harness boundary while retaining the current skill's strongest functional pieces: Camoufox, semantic refs, action feedback, profiles, handover, and local browsing knowledge.

## Sources

### Local

- [`agent/skills/browser/SKILL.md`](../agent/skills/browser/SKILL.md)
- [`agent/core/default-skills.txt`](../agent/core/default-skills.txt)
- [`agent/core/claude_runtime.py`](../agent/core/claude_runtime.py)
- [`agent/skills/browser/cli/src/vesta_browser/cli.py`](../agent/skills/browser/cli/src/vesta_browser/cli.py)
- [`agent/skills/browser/cli/src/vesta_browser/daemon.py`](../agent/skills/browser/cli/src/vesta_browser/daemon.py)
- [`agent/skills/browser/cli/src/vesta_browser/helpers.py`](../agent/skills/browser/cli/src/vesta_browser/helpers.py)
- [`agent/skills/browser/cli/src/vesta_browser/snapshot.py`](../agent/skills/browser/cli/src/vesta_browser/snapshot.py)
- [`agent/skills/browser/cli/src/vesta_browser/handover.py`](../agent/skills/browser/cli/src/vesta_browser/handover.py)

### External

- [Hermes browser guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/browser)
- [Hermes Browser Use adapter](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/tools/browser_use_cli.py)
- [Hermes model tool gating](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/model_tools.py)
- [Hermes browser provider registry](https://github.com/NousResearch/hermes-agent/blob/63279301bcbdc185c1b07b98a9312eb0c862f26d/agent/browser_registry.py)
- [Browser Use CLI](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/browser_use/cli.py)
- [Browser Use package metadata](https://github.com/browser-use/browser-use/blob/fe5ad353091fa2ed5499b94e8fe21094bc2e9e5a/pyproject.toml)
- [Browser Harness executor](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/run.py)
- [Browser Harness daemon](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/daemon.py)
- [Browser Harness helpers](https://github.com/browser-use/browser-harness/blob/10b2086c29f0696a6712956d2914e03012f5ebd0/src/browser_harness/helpers.py)
