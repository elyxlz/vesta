# Mobile visual runners

Runner details for the mobile family. The system, the gallery, and the registry contract are documented in `../../visual/README.md`.

Two runners share one registry (`visual/scenarios.json`), one set of Metro substitutions and fixtures (`visual/metro.config.js`, `visual/harness/`), and one set of Maestro flows (`maestro/visual/`): `scripts/visual-ios.mjs` captures on two iPhone simulators, `scripts/visual-android.mjs` captures on one Android emulator per variant. Both write into the shared store through `putShot`. `scripts/visual-runner.mjs` holds the helpers both use.

Reference targets: iPhone 17 on iOS 26.4; the `vesta-visual` AVD (Pixel 7 profile, API 36, arm64) for gesture navigation and `vesta-visual-galaxy` for 3-button navigation.

## Commands

From `apps/`:

```sh
# iOS: capture pages and detailed states on two simulator shards.
npm run mobile:visual:capture -- --device "iPhone 17"

# Android: capture one variant per run.
npm run mobile:visual:android:capture
npm run mobile:visual:android:capture -- --variant android-galaxy
```

Options:

```sh
# Reuse the installed visual app without rebundling JavaScript.
npm run mobile:visual:capture -- --device "iPhone 17" --skip-build

# Regenerate the cached native project (and, on iOS, the derived data).
npm run mobile:visual:capture -- --device "iPhone 17" --clean-native

# Show Simulator.app or the emulator window while capturing.
npm run mobile:visual:capture -- --device "iPhone 17" --show-simulator
npm run mobile:visual:android:capture -- --show-emulator

# Trade wall time for machine responsiveness.
npm run mobile:visual:capture -- --gentle

# Android: a specific AVD or an already-connected adb device.
npm run mobile:visual:android:capture -- --avd my-avd
npm run mobile:visual:android:capture -- --device emulator-5554
```

`--skip-build` is safe only when the installed visual app already contains the current JavaScript bundle. Do not use it after changing application or harness source unless another run has already installed those changes.

The page flows live in `maestro/pages/`, one clean deep link per page. Default captures also include detailed feature states under `maestro/visual/`. Use `npm run visual:capture -- ios --page settings` from `apps/` for a focused refresh, or `--page agent-chat-conversation` to target a state. `--suite pages` / `--suite states` narrow coverage on the shared CLI; direct runners use `VISUAL_SUITE`. Ensure **both** iOS shards have the current bundle when using `--skip-build`.

A focused state refresh runs its whole Maestro flow and records all of that flow's platform-supported screenshots. Other flows remain unselected; sibling captures are never discarded as unexpected screenshots.

Cold-linked sheets rely on the app's real Expo Router anchors: the root and agent stacks retain their index screens, and the pathless connection group retains its landing screen. Without an anchor, native-stack presents the first route as a card even when it requests a form sheet. Keep this in production routing, not a harness substitution. Route fingerprints include pathless layouts and anchor screens because those screens contribute the backdrop pixels.

Agent settings, detail sections, logs, notifications, and the file editor share one pathless `(settings)` navigator presented as a native sheet above the agent page. Its `settings` anchor preserves the back destination when a detail URL is opened directly. The inner routes push within that sheet; they do not depend on a previous manual visit to Settings to inherit modal presentation. Their public URLs are unchanged.

`maestro/navigation/agent-sheet.yml` separately checks the direct-link and normal Settings navigation round trip against the installed visual app (`maestro --device=<id> test maestro/navigation/agent-sheet.yml -e APP_ID=com.vesta.mobile.visual`). Its functional assertions never gate the screenshot flows. Run it only when the device is not capturing. Native build and clean-prebuild validation also need separate runs because both temporarily own `mobile/android` and `mobile/ios`.

General is folded into main agent Settings, with a dedicated Name panel at `details/name` and collapsed Technical details beside Logs. `page-agent-name` covers the rename destination; `agent-identity.yml` captures expanded technical details and a rename draft. The separate `maestro/navigation/agent-identity.yml` checks the legacy General redirect, cancelling a rename, disclosure toggling, and returning from the file editor.

`maestro/navigation/connect-scanner.yml` checks opening the scanner from a focused connection field, closing the denied-camera sheet, and submitting the preserved invalid link. The invalid-link screenshot starts from its own clean launch so it cannot accidentally capture a scanner left above the form. Navigation assertions stay in the separate round-trip test.

`maestro/visual/scan-ready.yml` independently grants camera access and opens the scanner directly. Refreshing `scan-ready` does not replay the denied-camera or invalid-link flow.

Scrollable page flows call `capture-page.yml`: it captures each new viewport in both themes and stops when another swipe produces identical stable pixels. The bridge returns whether another section is needed, and writes the page's freshness record only after reaching the end. A 24-viewport cap fails incomplete pages. `refs` and the gallery expose every part. The harness fixes wall time to 2026-08-01 09:41 UTC without freezing timers, so relative dates stay deterministic.

Those flows set `visualScroll=page`. The harness keeps the real native ScrollView but advances each drag by exactly three quarters of its viewport, with overlap and a final step clamped to the bottom. Gesture momentum cannot choose different offsets or skip sections between runs. Other flows and horizontal pagers retain their own scrolling behavior. Documentation and registry-only edits do not force a JavaScript rebundle. Android visual builds bound Gradle to four workers and 1 GB of metaspace; the Expo default of 512 MB cannot compile this native dependency graph reliably.

Native and config changes invalidate the native cache automatically. `--clean-native` is an explicit recovery option: it is not needed for ordinary React Native UI work, but it is the fix after the checkout moves, because Xcode's module cache pins absolute paths.

`--gentle` runs one simulator shard instead of two and every child process (build, bundler, Maestro, the emulator) at utility QoS through `taskpolicy`, so a capture can run behind interactive work.

## How an iOS capture runs

### 1. Prepare two simulators

The runner resolves the requested device and runtime, then creates or reuses two dedicated devices named `Vesta Visual 1` and `Vesta Visual 2`. Simulator.app does not show a window unless `--show-simulator` is passed; CoreSimulator still runs both devices and exposes their framebuffers to Maestro. The focused input scenario briefly uses a hidden, non-frontmost Simulator host to request the real software keyboard, then closes that host when capture ends.

The runner normalizes appearance, Dynamic Type size, and status bar data so captures remain comparable. Android demo mode pins Wi-Fi to full strength and omits cellular activity icons, which otherwise change pixels and confuse end-of-page detection; hiding both also triggers Android 16's delayed satellite fallback icon. Clock, battery, and system insets remain. Page flows share platform-specific permission setup in `prepare-page.yml`; scanner flows handle OS camera denial separately.

### 2. Build the isolated visual app

The first run generates an isolated native iOS project and builds the visual app through Xcode. The cache lives under:

```text
mobile/.visual/native/ios
mobile/.visual/native/fingerprint.txt
mobile/.visual/derived-data
```

The fingerprint covers Expo config, package manifests and lockfile, config plugins, native theme tokens, and native launch and icon assets. Changing one of those inputs invalidates and regenerates the native cache. The temporary native-project swap is transaction-backed: `Ctrl-C`, sleep, or a crashed process is restored during cleanup, and an unfinished swap is recovered at the start of the next run before any build work begins.

Normal JavaScript, TypeScript, and asset changes use a faster path:

```text
Expo/Metro export
  -> replace main.jsbundle and assets in the cached .app
  -> codesign
  -> install on both simulators in parallel
```

This avoids an Xcode rebuild during the normal polish loop.

### 3. Inject deterministic infrastructure

`visual/metro.config.js` substitutes modules such as:

- Privacy state
- Authentication and gateway API calls
- Recent gateway storage
- Boot splash timing
- Animated transitions that would make capture timing unstable

Fixtures match the production module's public contract. Production views render exactly as they normally would; only their inputs and side effects change.

### 4. Run Maestro flows across two simulators

The registry's `flows` list is split across the two simulators with `--shard-split=2`. Each deep link runs `wait-for-launch.yml`, which waits for the visual-only stack's `visual-harness-ready` signal after boot handoff. This gates JS/font startup without depending on any production control or text. Maestro uses visible text and accessibility labels to navigate; the screenshot bridge waits for stable pixels before recording the full-device screenshot. Final assertions about copy or component presence belong in functional tests, so removing a component produces a reviewable image change.

Visual builds replace app-level Reanimated transitions with instant values, force Expo Router stack transitions to `animation: "none"`, and inject `UIView.setAnimationsEnabled(false)` into the generated visual-only iOS AppDelegate. The iOS native activity indicator is held on its stopped frame (still visible, with its real size and color), since its indefinite animation ignores the UIKit switch. This disables both navigation and UIKit transitions without changing the production native project or application source. Native sheet detents are covered by the same pixel-stability check as the rest of the screen.

### 5. Write shots in both themes and warn on drift

Each flow step calls `capture-screenshot.js`, which POSTs to a local bridge (`CAPTURE_URL_1` and `CAPTURE_URL_2`, one per shard; the bridge itself is shared with the Android runner in `scripts/visual-runner.mjs`). On each callback the bridge grabs the framebuffer with `simctl io screenshot` and writes it with `putShot("ios", name, image)`, then flips the simulator to `appearance dark`, requires byte-identical grabs for at least 250 ms (failing after eight seconds if the screen never settles), writes the dark grab under `ios-dark`, and flips back to light before answering, so the flow continues where it was. The app follows the system appearance (`userInterfaceStyle: "automatic"`, theme preference `system`), so no second drive is needed. After the run, the runner compares the produced names against the registry and warns about missing or unexpected names; drift never fails the run. Maestro's own report lands at `mobile/.visual/maestro/report.html`, which the gallery links as "iOS report".

## Why scenario groups use separate launches

Native form sheets retain presentation context. Moving directly from one mocked state into another sheet can carry a stale modal stack into the screenshot.

The flows isolate those concerns:

```text
Privacy launch
  -> initialization failure
  -> locked state
  -> authentication failure
  -> process ends

Fresh onboarding launch
  -> mocked privacy provider starts unlocked
  -> production /connect route renders normally
  -> production onboarding sheets are presented

Fresh connected launch
  -> mocked session and roster providers start connected
  -> production home, settings, and release routes render normally
```

The fresh visual launch uses the existing development scheme:

```text
vesta-dev://connect?visualPrivacy=unlocked
```

Only modules under `visual/harness/` interpret the visual query parameters (`visual/harness/launch-query.ts` reads them once). The production controllers and routes are unchanged. The flows also handle iOS's one-time confirmation for opening a custom scheme.

| Switch                   | Values                                                                                                        | Effect                                                                                                              |
| ------------------------ | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `visualPrivacy`          | `unlocked`, `opening`                                                                                         | Starts unlocked; `opening` never hydrates, so the launch splash holds. Absent: locked with an initialization error. |
| `visualSession`          | `connected`                                                                                                   | Session fixture with the stub API client.                                                                           |
| `visualRoster`           | `empty`, `loading`                                                                                            | Roster variants; absent: aria, nova, forge.                                                                         |
| `visualAgent`            | any `AgentStatus`, `booting`, `thinking`, `backing_up`, `restoring`                                           | Puts aria into that state.                                                                                          |
| `visualDashboard`        | `loaded`, `error`                                                                                             | aria's dashboard service, rendering the fixture page or a failed load.                                              |
| `visualServices`         | `voice`                                                                                                       | Registers a voice service on aria (microphone in the composer).                                                     |
| `visualReachable`        | `offline`                                                                                                     | Gateway unreachable.                                                                                                |
| `visualManaged`          | `true`                                                                                                        | Managed gateway (account section).                                                                                  |
| `visualDevices`          | `none`, `position`                                                                                            | No devices, or the phone carrying a reported place.                                                                 |
| `visualChannel`          | `beta`                                                                                                        | Beta release channel (prerelease notes visible).                                                                    |
| `visualGatewayUpdate`    | `available`, `required`                                                                                       | Update pill, or the blocking update sheet.                                                                          |
| `visualGatewayOperation` | `snapshotting`, `snapshotting-all`, `applying`, `update-restarting`, `failed`, `failed-generic`, `restarting` | One gateway operation per launch.                                                                                   |
| `visualGatewayUpdated`   | a version                                                                                                     | The "updated to" notice.                                                                                            |
| `visualSyncState`        | `app_behind`                                                                                                  | The app-behind screen.                                                                                              |
| `visualLive`             | `typing`, `pending`                                                                                           | On a connected session: a paced reply stream, or pending notifications on aria.                                     |
| `visualChat`             | `delivery`, `errors`, `markdown`, `long`                                                                      | aria's transcript variant.                                                                                          |
| `visualProvider`         | `none`, `unauthenticated`, `openai`, `openrouter`                                                             | aria's provider state; absent: signed-in Claude.                                                                    |
| `visualVoice`            | `unconfigured`                                                                                                | No speech providers.                                                                                                |
| `visualApi`              | `error`                                                                                                       | Every agent read fails (error states).                                                                              |
| `visualDelay`            | milliseconds                                                                                                  | Holds pending answers (loading and in-flight states).                                                               |
| `visualLogs`             | `empty`, `error`                                                                                              | The log stream variant.                                                                                             |
| `visualReleaseNotes`     | `empty`, `error`                                                                                              | Release notes variant.                                                                                              |
| `visualWhatsNewSeen`     | a version                                                                                                     | Seeds the last-seen marker so the release notes auto-open.                                                          |
| `visualRecentGateways`   | `none`                                                                                                        | No saved gateways.                                                                                                  |
| `visualTunnel`           | `unavailable`                                                                                                 | No public tunnel.                                                                                                   |

nova is the agent with nothing yet (no notifications, rules, backups, mounts, or files), so its sections render the empty states; forge has no chat hold, so it renders the loading skeleton.

For future modal groups, prefer a fresh launch with deterministic initial data over navigating backward through several native sheets.

## The Android runner

`scripts/visual-android.mjs` reuses the whole system: the same registry, the same Metro substitutions and fixtures, and the same Maestro flows. Only the platform mechanics differ:

- One dedicated emulator per variant instead of two simulator shards. The runner reuses a booted AVD or boots it headless, and leaves it running. Create the AVDs once in Android Studio or with `avdmanager`. `--show-emulator` boots with a window for interactive diagnosis.
- `--variant android` (default) runs gesture navigation; `--variant android-galaxy` runs its own AVD with the classic 3-button bar, so every screen is exercised with a visible bottom navigation bar and its status bar insets. Each variant is its own platform in the store and the gallery.
- The build is a release APK through the generated visual Gradle project, so the visual JavaScript bundle is embedded. The project is cached at `.visual/native/android` with the same fingerprint inputs as iOS and swapped in and out of `android/` transactionally; production prebuilds are restored untouched. There is no separate fast-rebundle path: JavaScript changes go through the incremental Gradle build.
- Screenshots come from the same bridge as iOS: `capture-screenshot.js` POSTs to `CAPTURE_URL`, and the runner grabs the framebuffer with `adb exec-out screencap -p`, writes it under the variant, flips night mode with `cmd uimode night yes`, waits for the picture to settle, writes the dark grab under `<variant>-dark`, and flips back. The Activity declares `uiMode` in `configChanges`, so the flip re-themes in place. Maestro's `takeScreenshot` stays as the report artifact. The software keyboard renders inside the framebuffer, so the keyboard action is a no-op here.
- The status bar is normalized through Android demo mode (9:41, full wifi, full battery, no notifications) and animations are disabled with the global animation scales, mirroring the iOS status-bar override and animation hooks. The runner also enables the centred display-cutout emulation overlay, so the status bar and the app's content sit below the camera as they do on a Pixel or a Galaxy; the stock system image has no cutout and would lay the status bar flush into the corners.
- The runner warns about names that drift from the registry.
- The Maestro report lands at `mobile/.visual/<variant>/maestro/report.html` (`mobile/.visual/android/maestro/` for the default variant), which the gallery links as "Android report" and "Android · 3-button report".

## Only what changed

A capture plans before it runs (`planFlows` in `scripts/visual-runner.mjs`): for each flow it computes the sources its routes reach in Metro's dependency graph (`scripts/visual-sources.mjs`), fingerprints them with the flow text, the capture mechanics, the native inputs, and the flow's cards, and skips the flow when every shot it takes on the platform already carries that fingerprint in both themes. The bridge writes the record beside each shot it takes. `plan` prints the decision as JSON; `--all` retakes everything. The shared rules live in `apps/visual/README.md`.

## Platform-aware scenarios

An entry in `visual/scenarios.json` accepts an optional `platforms` array naming any mobile platform (`ios`, `android`, `android-galaxy`, and their `-dark` siblings). A scenario marked `"platforms": ["ios"]` is not expected from an Android capture, and the gallery renders its Android slots with an explicit "iOS only" note. The flows skip those captures through `runFlow` blocks conditioned on `when: platform`, so one flow file drives both platforms. Three shipped scenarios are iOS only (`connect-link-revealed`, `agent-pager-notifications`, `agent-pager-logs`): the reveal toggle after a capture and the Compose switches inside the agent settings sheet do not take Maestro's tap on Android.

The privacy gates and relock states capture on both platforms; on Android they present full screen through `SheetGateScreen` instead of a form sheet, and the unlock label carries the platform authentication name, so the flows match it by the "Unlock" prefix. The sheet close control is addressable by its accessibility label on both platforms, so the flows wait on and tap "Close settings" / "Close scanner" without platform blocks.

State flows share `prepare-page.yml` for platform-specific location permissions after a reset. The visual readiness marker also wraps compatibility gates that replace the navigator. Native text inputs retain their real layout, focus, selection, and keyboard, but the visual-only wrapper hides the blinking caret so focused-input screenshots can settle without weakening the pixel check.

Attachment fixtures use Expo's asset-loading lifecycle to resolve bundled media to real local files, including Android's embedded resources. Degraded fixtures still go through the production media error UI. Android setup closes only the visual app before normalizing SystemUI, so an animated or focused screen left by a previous flow cannot block the next run before it starts.

## Add a screenshot to an existing flow

### 1. Reach a deterministic state

Add navigation and interactions to the appropriate file under `maestro/visual/`. Prefer semantic text and existing accessibility labels over coordinates.

Keep state-based waits where a following interaction depends on a navigation target. Do not assert surrounding copy, icons, or disabled state just to take a screenshot. Capture itself waits on pixels:

```yaml
- extendedWaitUntil:
    visible: "Control used by the next action"
    timeout: 10000
```

### 2. Capture on both platforms

Every screenshot needs both commands:

```yaml
- takeScreenshot: example-state
- runScript:
    file: capture-screenshot.js
    env:
      SCREENSHOT: example-state.png
```

`takeScreenshot` keeps the Maestro report artifact. The script notifies the bridge, which writes the shot in both themes on both platforms. Omit the callback and no shot is written.

### 3. Register the scenario

Add a matching entry to `visual/scenarios.json`:

```json
{
  "id": "example-state",
  "title": "Example state",
  "description": "What this state is intended to verify.",
  "group": "Onboarding"
}
```

The screenshot name defaults to `<id>.png` and must match the PNG the flow captures.

### 4. Verify

```sh
npm run mobile:check
npm -w @vesta/mobile run lint
npm run mobile:visual:capture -- --device "iPhone 17"
```

Open the gallery and inspect the actual pixels. A passing selector proves that Maestro found the expected element; it does not prove that surrounding navigation, sheet presentation, safe areas, or dimming are visually correct. A theme capture fails if consecutive framebuffer grabs do not stabilize within eight seconds. The runner restores light appearance even when the dark capture fails, and writes the freshness record only after both themes and the restoration succeed.

## Add deterministic mock data

Add a fixture when a production screen depends on live APIs, device services, persistent state, nondeterministic timing, or unavailable credentials.

### 1. Mock the infrastructure boundary

Create a module under `visual/harness/` with the same public contract as the production module. It may import production types, but it must not import a visual component into production code.

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

### 2. Register the substitution

Add the production import and fixture path to the map in `visual/metro.config.js`:

```js
[
  "@/profile/profile-store",
  path.resolve(__dirname, "harness/profile-store.ts"),
],
```

If production code imports the same module through both an alias and a relative path, the resolver must cover both forms. Do not change production imports to make the harness easier to wire.

### 3. Model useful transitions

Fixtures are deterministic but may still model time and state:

- Return a fixed list for a populated screen.
- Throw a fixed error for a recovery state.
- Use a short delay when the screenshot needs a visible loading state.
- Keep small module or provider state when a Maestro action must transition the view from one state to another.

Do not mock the screen component itself. If a screen is too coupled to mock at an infrastructure boundary, refactor production toward ordinary provider, controller, and presentation boundaries that improve the real app as well. Do not add a capture-only controller.

## Add another top-level flow

Add screenshots to an existing flow whenever the launch context is compatible. Good reasons for a new top-level flow:

- The state requires a fundamentally different clean launch.
- The flow would otherwise depend on the result of another flow.
- The new scenario group needs its own app process or permission setup.

Keep flows independent: no flow may depend on another simulator having run first. Register the file in the registry's `flows` list; the order is the shard order, so keep the two shards balanced.

## Selector and scenario guidelines

- Prefer visible text or meaningful accessibility labels.
- Use regular expressions only when dynamic copy requires them.
- Use coordinates only for controls that cannot expose a stable semantic target.
- Let the bridge wait for stable pixels; use selectors only to reach the state being captured.
- Keep dates, gateway names, and error messages fixed in fixtures.
- Use unique screenshot names across all flows.
- Capture meaningful UI states, not every intermediate animation frame.
- Keep each scenario understandable from its title and description alone.
- Use a fresh launch when native modal history could contaminate the state.

Adding a useful accessibility label to production can be a legitimate product improvement. Adding a label whose only meaning is "the screenshot bot needs this" violates the boundary.

## Troubleshooting

### The visual app is not installed

Run without `--skip-build`.

### Java or Maestro is missing

Install Java 17 or newer and Maestro:

```sh
brew tap mobile-dev-inc/tap
brew install mobile-dev-inc/tap/maestro
```

### Native changes do not appear, or xcodebuild fails after the checkout moved

Regenerate the isolated native cache with `--clean-native`.

### A flow times out

Inspect:

```text
mobile/.visual/maestro/report.html
mobile/.visual/maestro/**/screenshots/
mobile/.visual/maestro/**/screen-hierarchy/
mobile/.visual/maestro/**/logs/
```

The failure screenshot and accessibility hierarchy usually show whether the app is on the wrong route, behind a system dialog, or waiting for different copy. For Android, the same tree lives under `mobile/.visual/<variant>/maestro/`.

### A modal screen appears inside another sheet

Treat this as a navigation-state problem, not a styling problem. Verify that:

- The base screen starts from a clean process.
- A previous native sheet was actually dismissed.
- The harness is not replacing or pushing production routes.
- Independent visual states use independent launches.

The visual harness controls data; it does not reimplement the production router.

### A new iOS Simulator asks to open the deep link

The flows include an optional handler for iOS's "Open in Vesta Dev?" prompt. If a new iOS version changes that system copy, update the system-dialog selector in the flows rather than adding logic to the mobile app.
