---
name: visual-qa
description: Operate and extend Vesta's deterministic visual QA system for every app. Use when capturing or serving the gallery, adding or updating scenarios for mobile (Maestro) or web and desktop (Playwright), creating visual-only fixtures, diagnosing a capture, or reviewing a change against the production boundary.
---

# Visual QA

## Establish context

Work from `apps/`.

Read these live sources before changing the system:

1. Read `visual/README.md` completely: the system, the platform table, the registry contract, the gallery, and troubleshooting.
2. Read `visual/platforms.mjs`: the one owner of which platforms, runners, and families exist.
3. Read the registry you are extending: `mobile/visual/scenarios.json` or `web/visual/scenarios.json`.
4. Read the runner README for that family: `mobile/visual/README.md` or `web/visual/README.md`.
5. Read the affected flow (`mobile/maestro/visual/*.yml`) or drive (`web/visual/drives.ts`), and the harness module that mocks the data (`mobile/visual/harness/`, `web/visual/harness/`).
6. Read the production route and its infrastructure dependencies, so the real rendering path is preserved.

Treat the repository files as authoritative if details in this skill become stale.

## Preserve the non-negotiable boundary

Keep all capture orchestration and visual-only behavior outside `mobile/app/`, `mobile/src/`, `web/src/`, `desktop/src/`, and checked-in native code.

Never add any of the following to production application code:

- Capture flags or screenshot environment checks
- Routes, controllers, or rendering branches that exist only for a screenshot
- Imports from `visual/` or `maestro/`
- Fake screen copies or alternate visual components
- Accessibility labels or test ids whose only meaning is for the screenshot bot

Render the production route, screen, navigation stack, sheet presentation, safe areas, and controls. Mock only infrastructure inputs and side effects through the family's harness. Frames (the phone bezel, the browser bar, the desktop title bar) are gallery CSS, never baked into a PNG.

Refactor production code only when the change creates a generally useful boundary, such as separating a provider, controller, service, or presentation component. Do not create a capture-only abstraction. The mobile runner's `assertHarnessBoundary()` is a guardrail, not a complete policy checker.

## Understand the system

Data path:

```text
mobile runners (Maestro)      web runner (Playwright)
        |                              |
        +--- putShot(platform, id) ----+
                      |
                      v
    apps/visual/.visual/shots/<platform>/<id>.png
                      |
                      v
   gallery on 127.0.0.1:4173, composed per request from
   both scenarios.json files plus the store
```

Ownership:

| Path | Responsibility |
| --- | --- |
| `visual/platforms.mjs` | Platforms, runners, families |
| `visual/registry.mjs` | The scenario contract, both families |
| `visual/store.mjs` | Shot paths, `putShot`, the shot index, the drift warning |
| `visual/run-status.mjs` | The capture phase file the gallery polls |
| `visual/gallery/` | Server, view model, page, styles, client script |
| `visual/cli.mjs` | `serve` and `capture <runner>` |
| `mobile/visual/scenarios.json`, `mobile/maestro/visual/`, `mobile/visual/harness/`, `mobile/scripts/visual-*.mjs` | The mobile family |
| `web/visual/scenarios.json`, `web/visual/drives.ts`, `web/visual/harness/`, `web/visual/capture.spec.ts` | The web family |
| `visual/.visual/` | Ignored: `shots/`, `run-status.json`, `capture-<runner>.log` |

Platforms: `ios`, `android`, `android-galaxy` (mobile family); `web`, `desktop`, `web-narrow` and their `-dark` variants (web family). Runners: `ios`, `android`, `android-galaxy`, `web`. A theme variant is its own platform. The Web runner fills all six web platforms in one Playwright run.

There is no watch mode. Recapture is a Scan button in the gallery or `npm run visual:capture -- <runner>`.

## Choose the smallest extension

Use this order:

1. Add a screenshot to an existing flow or an entry to the web registry when the state is reachable from that flow's clean launch.
2. Extend an existing harness fixture when only data or a side effect differs.
3. Add a new harness substitution or route when the production dependency is nondeterministic or unavailable.
4. Add a top-level mobile flow only when the state requires a separate clean launch, permission setup, session mode, or native modal history.
5. Change `@vesta/visual` only when the platform table, the contract, the store, or the gallery itself must change.

## Add a screenshot state

### 1. Trace the real screen

Identify the production route, how users navigate to it, the provider, service, and storage modules it consumes, and the visible state that proves it is ready.

### 2. Make inputs deterministic

Reuse a fixture when possible. Otherwise create one with the exact public contract of the production module (mobile: a module under `mobile/visual/harness/` registered in `mobile/visual/metro.config.js`; web: a route in `web/visual/harness/http-fixtures.ts` or a frame in `sync-fixtures.ts`). Keep fixture values stable and visually meaningful. Model only the transitions the public UI needs: fixed data for populated and empty states, a fixed error for a recovery state, a deterministic delay only for a real loading state.

Do not replace the screen component.

### 3. Drive the public UI

Mobile: add commands to the right `mobile/maestro/visual/*.yml`. Wait on the state being captured, not elapsed time:

```yaml
- extendedWaitUntil:
    visible: "Expected screen title"
    timeout: 10000
- takeScreenshot: example-state
- runScript:
    file: capture-screenshot.js
    env:
      SCREENSHOT: example-state.png
```

Both commands are required: `takeScreenshot` feeds the Android runner, the callback feeds the iOS bridge. For a real focused keyboard use the bridge action `ACTION: show-software-keyboard` before capture; never draw a fake keyboard.

Web: add `drive` and `settle` under the scenario id in `web/visual/drives.ts`. `settle` is an assertion on the captured state, never a bare sleep.

### 4. Register the scenario

Add exactly one entry to the family's `scenarios.json`:

```json
{
  "id": "example-state",
  "title": "Example state",
  "description": "The visual behavior this state verifies.",
  "group": "Onboarding"
}
```

`screenshot` defaults to `<id>.png`. Add `"platforms": [...]` only when the state genuinely cannot exist on some platform of its family; on mobile, wrap the flow steps in a matching `when: platform` block. Ids and screenshot names are unique across both families.

### 5. Verify

```sh
./check.sh app-visual
npm run mobile:visual:capture -- --device "iPhone 17"     # or
npm run web:visual:capture
npm run visual
```

Inspect the actual gallery pixels at `http://127.0.0.1:4173`, not only the runner's pass result: the frame, safe areas, status bar, keyboard, theme, sheet corners, and neighboring content.

## Run the system

From `apps/`:

```sh
npm run visual                                   # serve and open the gallery
npm run visual:serve                             # serve without opening
npm run visual:capture -- ios|android|android-galaxy|web [--gentle]
npm run mobile:visual:capture -- --device "iPhone 17"
npm run mobile:visual:android:capture -- --variant android-galaxy
npm run web:visual:capture -- --project web-dark
```

Runner options: `--skip-build` (reuse the installed app when nothing changed), `--clean-native` (regenerate the native cache), `--show-simulator` / `--show-emulator` (interactive diagnosis), `--gentle` (background priority, one shard).

## Diagnose failures

Use the gallery's status pill first, then:

```text
visual/.visual/capture-<runner>.log
visual/.visual/run-status.json
mobile/.visual/maestro/report.html                     (iOS)
mobile/.visual/<variant>/maestro/report.html           (Android)
web/.visual/report/index.html                          (web)
```

- Timed out screenshot names: find the first failed Maestro step; later missing PNGs are downstream.
- Tap completes but the route does not change: wait for the prior async state, assert the destination, retry only on visible state.
- Sheet content or bottom gutter clipped: assert the final content and wait for the detent to settle. Do not patch production spacing until reproducing outside the harness.
- A sheet appears inside the wrong sheet: start a clean flow; fix navigation history, not styling.
- Keyboard absent (iOS): confirm focus, then that the `show-software-keyboard` action reached the bridge.
- Native changes stale, or `xcodebuild exited with 65` after the checkout moved: `--clean-native`.
- Web: `browserType.launch: Executable doesn't exist`: `npx playwright install chromium` in `apps/web`.
- Web: a `settle` fails: read the Playwright report; that scenario keeps its previous shot.
- Port 4173 busy: stop the other gallery or pass `--port`.

Do not weaken the registry or delete scenarios to silence a drift warning; fix the flow or drive that stopped producing the shot.

## Review every visual-suite change

Confirm all of the following before handoff:

- Production routes and views remain the rendered implementation.
- No capture logic entered `mobile/app/`, `mobile/src/`, `web/src/`, `desktop/src/`, or checked-in native code.
- Fixtures match production contracts and contain deterministic values.
- Selectors are semantic and waits assert the captured state.
- Every mobile `takeScreenshot` has its callback and registry entry; every web registry id has a drive (`web/visual/registry.test.ts`).
- Screenshot names are unique across both families and metadata is useful.
- Native sheets start from a clean presentation context and are fully settled.
- Headless behavior, real keyboard capture, and animation suppression still work.
- One capture succeeds per runner you touched, and the gallery renders every slot in its frame.
- `./check.sh app-visual`, the family's `check.sh` slice, and `git diff --check` pass.
- Generated `.visual/` artifacts remain ignored and uncommitted.
