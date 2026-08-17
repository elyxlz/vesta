---
name: mobile-visual-qa
description: Operate and extend Vesta's deterministic mobile visual QA system. Use when Codex needs to capture or serve the iOS or Android screenshot gallery, add or update screenshot scenarios and Maestro flows, create visual-only fixtures for screens or UI states, diagnose screenshot timeouts, native sheets, keyboards, simulators, emulators, watch mode, or gallery failures, optimize headless or sharded captures, or review changes against the strict production-boundary rule.
---

# Mobile Visual QA

## Establish context

Work from `apps/mobile` unless a command explicitly targets the `apps` workspace.

Read these live sources before changing the system:

1. Read `visual/README.md` completely for the current architecture and commands.
2. Read `visual/scenarios.json` for the registered flow and screenshot contract, including per-scenario `platforms`.
3. Read `visual/metro.config.js` and the relevant module under `visual/harness/` when data is mocked.
4. Read the affected `maestro/visual/*.yml` flow.
5. Read the production route and its infrastructure dependencies to preserve the real rendering path.
6. Read the relevant section of `scripts/visual-catalog.mjs` before changing build, simulator, sharding, watch, capture, or gallery behavior, and `scripts/visual-catalog-android.mjs` before changing Android emulator, build, or capture behavior.

Treat the repository files as authoritative if details in this skill become stale.

## Preserve the non-negotiable boundary

Keep all screenshot orchestration and visual-only behavior outside `app/`, `src/`, and the checked-in `ios/` project.

Never add any of the following to production application code:

- Capture flags or screenshot environment checks
- Maestro-only routes, controllers, or rendering branches
- Query-parameter branches whose only purpose is a screenshot
- Imports from `visual/` or `maestro/`
- Fake screen copies or alternate visual components
- Accessibility labels whose only meaning is for the screenshot bot

Render the production route, screen, navigation stack, sheet presentation, safe areas, and controls. Mock only infrastructure inputs and side effects through `visual/metro.config.js` and `visual/harness/`.

Refactor production code only when the change creates a generally useful boundary, such as separating a provider, controller, service, or presentation component. Do not create a capture-only abstraction. The runner's `assertHarnessBoundary()` is a guardrail, not a complete policy checker.

## Understand the system

Follow this data path:

```text
Production routes and views
        +
Visual-only infrastructure substitutions
        |
        v
Isolated cached iOS app + fast Metro rebundles
        |
        v
Two headless iPhone 17 / iOS 26.4 CoreSimulator devices
        |
        v
Maestro flows split across two shards
        |
        v
simctl framebuffer screenshots + completion bridge
        |
        v
Shot files replaced in place under .visual/shots/
        |
        v
Localhost gallery composed from the registry + shots
```

Know the ownership of each path:

| Path | Responsibility |
| --- | --- |
| `app/`, `src/` | Production routes, views, controllers, providers, and services |
| `visual/scenarios.json` | Required flows and exact screenshot metadata contract |
| `visual/metro.config.js` | Visual-build-only module resolution and substitutions |
| `visual/harness/` | Deterministic provider, API, storage, session, animation, and native-build fixtures |
| `maestro/visual/*.yml` | Public-UI navigation, permissions, assertions, transitions, and capture points |
| `maestro/visual/capture-screenshot.js` | Screenshot/action callback to the local bridge |
| `scripts/visual-catalog.mjs` | Builds, simulators, sharding, watch cancellation, drift warnings, and the gallery server |
| `.visual/` | Ignored generated app, native cache, Maestro reports, and the shot registry at `.visual/shots/{ios,android}/` |

The first capture may generate an isolated iOS project and perform an Xcode build. Ordinary TypeScript, JavaScript, harness, and asset changes use a fast Metro export, replace the cached app bundle, codesign it, and install it on both simulators.

The normal runner does not display Simulator.app. CoreSimulator renders offscreen framebuffers. The real iOS keyboard is host-controlled, so the focused-input scenario briefly starts Simulator hidden and non-frontmost, toggles the software keyboard, and terminates the host after capture. Use `--show-simulator` only for interactive diagnosis.

The visual build removes motion at three boundaries:

- `visual/harness/reanimated.js` resolves app-level Reanimated work immediately.
- `visual/harness/stack.js` forces Expo Router stack transitions to `animation: "none"`.
- `visual/harness/disable-ios-animations.swift` is injected into only the generated visual AppDelegate and disables UIKit animations.

Still assert settled UI state before capture. Native form-sheet detents can resize after content becomes accessible even when transition animations are disabled.

## Choose the smallest extension

Use this order:

1. Add a screenshot to an existing flow when the state is reachable from that flow's clean launch.
2. Extend an existing harness fixture when only data or a side effect differs.
3. Add a new harness substitution when the production dependency is nondeterministic or unavailable.
4. Add a top-level flow only when the state requires a separate clean launch, permission setup, session mode, or native modal history.
5. Change the runner only when the execution topology itself must change.

Prefer a fresh launch over navigating backward through a long native sheet stack. Keep every top-level flow independent of other flows and simulators.

## Add a screenshot state

### 1. Trace the real screen

Identify the production route, how users navigate to it, the provider/service/storage modules it consumes, and the visible state that proves it is ready. Preserve that route and interaction path in Maestro.

### 2. Make inputs deterministic

Reuse a fixture under `visual/harness/` when possible. Otherwise create one with the exact public contract of the production module:

```ts
import type { Profile } from "@/profile/types";

const profile: Profile = {
  id: "visual-profile",
  displayName: "Ada",
};

export async function readProfile(): Promise<Profile> {
  return profile;
}
```

Keep fixture values stable and visually meaningful. Use fixed names, dates, messages, versions, and IDs. Model only the state transitions required by public UI interactions:

- Return fixed data for populated and empty states.
- Throw a fixed error for recovery states.
- Use a deterministic delay only when capturing an actual loading state.
- Keep small module/provider state when one Maestro action must cause the next state.
- Stub credentials, network calls, storage, biometrics, and device services at their infrastructure boundary.

Do not replace the screen component.

### 3. Register the substitution

Map the production import to the fixture in `visual/metro.config.js`:

```js
[
  "@/profile/profile-store",
  path.resolve(__dirname, "harness/profile-store.ts"),
],
```

Match every import form actually used by consumers. For relative imports or consumer-specific substitutions, follow the existing `context.originModulePath` resolver patterns. Do not rewrite production imports solely for the harness.

### 4. Drive the public UI

Add commands to the most appropriate `maestro/visual/*.yml` file. Prefer visible text and meaningful accessibility labels. Avoid coordinates unless no semantic selector exists.

Wait on the state being captured, not elapsed time:

```yaml
- extendedWaitUntil:
    visible: "Expected screen title"
    timeout: 10000
- waitForAnimationToEnd:
    timeout: 3000
```

Use `clearState`, a fresh deep link, and explicit permissions when prior native navigation or system state could contaminate the result. Retain the optional `^Open$` handler for iOS's custom-scheme confirmation where needed.

### 5. Capture and notify

Give every state a unique lowercase kebab-case name. Always pair the screenshot command with the bridge callback:

```yaml
- takeScreenshot: example-state
- runScript:
    file: capture-screenshot.js
    env:
      SCREENSHOT: example-state.png
```

The gallery shot comes from `xcrun simctl io ... screenshot`, triggered by the callback and written straight into `.visual/shots/ios/`, because it captures host-controlled UI such as the real keyboard reliably. Maestro's artifact remains useful in its diagnostic report. Omitting either command breaks an execution or diagnostic path.

For a real focused keyboard state, use the existing bridge action before capture:

```yaml
- tapOn: "Connection link"
- runScript:
    file: capture-screenshot.js
    env:
      ACTION: show-software-keyboard
- waitForAnimationToEnd:
    timeout: 3000
```

Do not draw or overlay a fake keyboard.

### 6. Register the manifest entry

Add exactly one matching item to `visual/scenarios.json`:

```json
{
  "id": "example-state",
  "title": "Example state",
  "description": "The visual behavior this state verifies.",
  "group": "Onboarding",
  "screenshot": "example-state.png"
}
```

Match `screenshot` exactly to the callback filename. Keep titles and descriptions understandable without reading the flow. The registry loader rejects duplicate ids and screenshot names; after a run, the runner warns about shot names that are missing from or unexpected against the registry, without failing the run. Add `"platforms": ["ios"]` only when the state genuinely cannot exist on Android, and wrap its flow steps in a matching `when: platform: iOS` block.

### 7. Verify the complete catalog

Run from `apps/`:

```sh
npm run mobile:check
npm -w @vesta/mobile run lint
npm -w @vesta/mobile test -- --run
npm run mobile:visual:capture -- --device "iPhone 17"
```

Inspect the actual gallery pixels at `http://127.0.0.1:4173`, not only Maestro's pass result. Verify the complete simulator frame, underlying presentation context, dimming, sheet corners and bottom gutter, safe areas, status bar, keyboard, theme, and neighboring content.

## Add or reshape top-level flows

Prefer adding states to an existing flow. Add a flow only for a genuinely independent launch context.

When adding one:

1. Create an independent `maestro/visual/<group>.yml` with `appId: ${APP_ID}`.
2. Establish clean app state and permissions inside that flow.
3. Add the path to `visual/scenarios.json` under `flows`.
4. Ensure all screenshot callbacks remain globally unique.
5. Inspect both one-shot and watch scheduling in `scripts/visual-catalog.mjs`.
6. Run one-shot capture and persistent watch before considering the change complete.

Do not assume one-shot sharding and persistent watch have the same scheduling model. One-shot mode delegates all manifest flows to Maestro with `--shard-split=2`; watch mode manages continuous Maestro processes itself. Treat any change to the flow count or assignment as a runner-level compatibility check.

## Run the system

Run from `apps/`:

```sh
# Capture, open the gallery, and keep the server alive.
npm run mobile:visual -- --device "iPhone 17"

# Watch source edits, cancel obsolete runs, and recapture the latest revision.
npm run mobile:visual:watch -- --device "iPhone 17"

# Capture and exit.
npm run mobile:visual:capture -- --device "iPhone 17"

# Serve the gallery from the registry and existing shots without capturing.
npm run mobile:visual:serve

# Android: capture on the vesta-visual AVD and serve on port 4174.
npm run mobile:visual:android
npm run mobile:visual:android:capture
npm run mobile:visual:android:serve
```

The gallery is one page for both platforms, composed per request from
`visual/scenarios.json` plus the shot files under `.visual/shots/`: each
scenario card shows its iOS and Android slots side by side, and every serve
command serves that same page. Each scan replaces its platform's shot files
in place (the iOS bridge writes them directly; the Android runner stages
Maestro's `takeScreenshot` artifacts into `.visual/shots/android/` after the
run), so a missing file renders "Not captured yet" until a scan produces it.
Scenarios marked `"platforms": ["ios"]` are skipped by `runFlow` platform
blocks in the flows and rendered as explicit "iOS only" Android slots. Read
the "Android catalog" section of `visual/README.md` before changing Android
behavior; keep every shared step identical across platforms and put a
platform difference inside a `when: platform` block, never in a copied flow
file.

Use these options deliberately:

- `--no-open`: Keep the browser from opening automatically.
- `--skip-build`: Reuse the already-installed bundle only when it is current.
- `--clean-native`: Regenerate the isolated iOS project after native-cache trouble.
- `--show-simulator`: Display Simulator.app for interactive debugging.
- `--port <number>`: Change the localhost gallery port.

Keep watch mode running during UI polish. It debounces edit bursts and cancels an obsolete Maestro run when newer edits arrive. Shots replace their files as they are captured; a failed or cancelled run leaves every shot it did not reach untouched.

## Diagnose failures

Use the portal error first, then inspect:

```text
.visual/maestro/report.html
.visual/maestro/**/screenshots/
.visual/maestro/**/screen-hierarchy/
.visual/maestro/**/logs/
.visual/shots/{ios,android}/
```

Apply these diagnoses:

- **Timed out screenshot names**: Find the first failed Maestro step. A later missing PNG is usually downstream, not an independent failure.
- **Tap completes but route does not change**: Wait for any prior async error/loading state to complete, assert the destination, and retry only based on visible state.
- **Sheet content or bottom gutter is clipped**: Assert the final content and then wait for the form-sheet detent to settle. Do not patch production spacing until reproducing outside the harness.
- **A sheet appears inside the wrong sheet**: Start a clean process or flow. Fix navigation history, not layout styling.
- **Keyboard is absent**: Confirm focus first, then confirm the `show-software-keyboard` action reached the correct shard callback. Do not replace it with Maestro's artifact or a fake keyboard.
- **Simulator windows appear**: Ensure `--show-simulator` is absent. The keyboard host must use hidden, non-frontmost launch semantics.
- **Wrong device/runtime**: Pass `--device "iPhone 17"` and verify catalog metadata reports iOS 26.4.
- **Native changes are stale**: Run once with `--clean-native`.
- **Portal reports failure after edits**: Leave watch alive, fix the first failed state, and save again.
- **Port is occupied or server slept**: Stop the stale server or use `--port`; restart `mobile:visual:serve` for an existing catalog.
- **Visual app crashes at launch**: Inspect the simulator log for the first unhandled JS/native exception. Check Metro fixture exports and module interop before blaming Maestro.

Do not weaken the registry or delete scenarios to silence a drift warning; fix the flow that stopped producing the shot.

## Review every visual-suite change

Confirm all of the following before handoff:

- Production routes and views remain the rendered implementation.
- No visual-capture logic entered `app/`, `src/`, or checked-in native code.
- Fixtures match production contracts and contain deterministic values.
- Selectors are semantic and waits assert captured state.
- Every `takeScreenshot` has its exact callback and manifest entry.
- Screenshot names are unique and metadata is useful.
- Native sheets start from clean presentation context and are fully settled.
- Headless behavior, real keyboard capture, and animation suppression still work.
- One-shot capture succeeds for every registered state on two iPhone 17/iOS 26.4 shards.
- Watch mode survives a source edit, cancellation, and a successful recapture when its scheduling was affected.
- Typecheck, lint, tests, formatting/guards, and `git diff --check` pass.
- Generated `.visual/` artifacts remain ignored and uncommitted.
