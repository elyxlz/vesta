# Mobile visual catalog

The mobile visual catalog renders the real Vesta iOS application with
deterministic, visual-only data providers, drives it with Maestro on two iOS
Simulators, captures every registered state, and serves the results in a local
browser gallery.

The system is intended for fast visual QA while building screens. It is local
only today; no GitHub Actions workflow is included yet.

## Quick start

From `apps/`:

```sh
# Capture once, open the gallery, and keep its server running.
npm run mobile:visual -- --device "iPhone 17"

# Recommended while editing: recapture whenever source files change.
npm run mobile:visual:watch -- --device "iPhone 17"
```

The gallery is served at:

```text
http://127.0.0.1:4173
```

The current reference target is two iPhone 17 simulators running iOS 26.4.
Passing `--device "iPhone 17"` makes the target explicit and lets the runner
create or reuse its dedicated two-simulator pair.

## What the system guarantees

- Screens and navigation come from the production application.
- Mock data and scripted failures stay under `visual/harness/`.
- Capture behavior stays out of `app/` and `src/`.
- Every scenario registered in the manifest must produce exactly one PNG.
- Watch mode publishes a new gallery only after the complete capture succeeds.
- A newer edit cancels an obsolete capture and discards its partial output.
- The two Maestro flows run in parallel on independent app processes.

## Architecture

```text
Production routes and UI
          +
Visual-only mocked infrastructure
          |
          v
Cached iOS application bundle
          |
          v
Two dedicated iOS Simulators
          |
          v
Two parallel Maestro flows
          |
          v
Staged screenshots + completion bridge
          |
          v
Validated catalog and localhost gallery
```

The important design choice is that the catalog does not maintain copies of
screens. Production components continue to call their normal providers,
storage modules, and API functions. The visual Metro configuration replaces
selected infrastructure modules when it builds the isolated visual app.

Ordinary Expo builds do not load the visual Metro configuration or its
fixtures.

## Directory map

| Path | Responsibility |
| --- | --- |
| `scripts/visual-catalog.mjs` | Simulator lifecycle, cached builds, Maestro execution, watch cancellation, validation, and gallery server |
| `visual/scenarios.json` | Catalog manifest: app ID, flow list, screenshot names, titles, descriptions, and groups |
| `visual/metro.config.js` | Visual-build-only module substitution |
| `visual/harness/` | Deterministic providers, APIs, storage, splash behavior, and animation adapters |
| `maestro/visual/*.yml` | User-visible navigation, interactions, assertions, and screenshot commands |
| `maestro/visual/capture-screenshot.js` | Notifies persistent watch mode that a named screenshot completed |
| `.visual/` | Ignored native cache, bundles, reports, screenshots, staging files, and generated gallery |

## Production boundary

Production code must never know that a visual capture is running. Do not add:

- Capture flags or environment checks in `app/` or `src/`
- Screenshot-specific routes
- Query-parameter branches in production screens
- Alternate rendering paths that exist only for Maestro
- Fixture imports from production modules

The runner scans TypeScript files under `app/` and `src/` before every capture
and rejects known harness markers. This is a guardrail, not permission to add
capture logic under a different name.

When a screen needs deterministic data, replace the infrastructure module in
`visual/metro.config.js`. The real screen, route, and presentation remain
unchanged.

## How a capture runs

### 1. Prepare two simulators

The runner resolves the requested device and runtime, then creates or reuses
two dedicated devices named `Vesta Visual 1` and `Vesta Visual 2`. Simulator.app
stays closed unless `--show-simulator` is passed; CoreSimulator still runs both
devices and exposes their framebuffers to Maestro.

The runner normalizes appearance, Dynamic Type size, and status bar data so
captures remain comparable. Maestro flows establish the scenario-specific
permissions they need.

### 2. Build the isolated visual app

The first run generates an isolated native iOS project and builds the visual
app through Xcode. The cache lives under:

```text
mobile/.visual/native/ios
mobile/.visual/native/fingerprint.txt
mobile/.visual/derived-data
```

The fingerprint covers Expo config, package manifests and lockfile, config
plugins, native theme tokens, and native launch/icon assets. Changing one of
those inputs automatically invalidates and regenerates the native cache.
The temporary native-project swap is transaction-backed: `Ctrl-C`, sleep, or a
crashed process is restored during cleanup, and an unfinished swap is recovered
at the start of the next run before any build work begins.

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

Fixtures match the production module's public contract. Production views render
exactly as they normally would; only their inputs and side effects change.

### 4. Run Maestro flows across two simulators

The manifest currently registers:

```text
maestro/visual/connect.yml
maestro/visual/recent-gateways.yml
maestro/visual/connected.yml
maestro/visual/connected-whats-new-empty.yml
maestro/visual/connected-whats-new-error.yml
maestro/visual/connected-home-empty.yml
```

The flows are split across two simulators. Maestro interacts through visible
text and accessibility labels, waits for a specific state, then takes a
full-device screenshot.

### 5. Validate and publish

`visual/scenarios.json` is the contract for the output set. The runner verifies
that every registered filename exists exactly once, reads image dimensions,
adds device and Git metadata, and generates:

```text
mobile/.visual/index.html
mobile/.visual/catalog.json
mobile/.visual/screenshots/<release>/*.png
mobile/.visual/maestro/report.html
```

Screenshot releases are immutable. The runner stages and validates the entire
set, writes the new gallery, and atomically commits `catalog.json` last, so a
failed or superseded capture cannot mix old and new images. Recent releases are
kept briefly so already-open browser pages can finish loading. All generated
content under `mobile/.visual/` is ignored by Git.
While the server is running, `/status.json` is a dynamic endpoint used by the
portal; it is not a generated file.

## Why scenario groups use separate launches

Native form sheets retain presentation context. Moving directly from one
mocked state into another sheet can accidentally carry a stale modal stack
into the screenshot.

The current flows isolate those concerns:

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

Only modules under `visual/harness/` interpret the visual query parameters.
The production controllers and routes are unchanged. The flows also handle
iOS's one-time confirmation for opening a custom scheme.

For future modal groups, prefer a fresh launch with deterministic initial data
over navigating backward through several native sheets.

## Everyday commands

Run commands from `apps/`.

### Capture, open, and serve

```sh
npm run mobile:visual -- --device "iPhone 17"
```

This captures the catalog, opens the browser, and keeps the server running.
Press `Ctrl-C` to stop it.

### Watch while editing

```sh
npm run mobile:visual:watch -- --device "iPhone 17"
```

Keep this process running. Saving a watched source file automatically updates
the portal to a recapturing state, rebuilds when needed, reruns both flows, and
refreshes the browser after a complete result is available.

### Capture and exit

```sh
npm run mobile:visual:capture -- --device "iPhone 17"
```

Use this for an explicit verification pass without keeping the gallery server
open.

### Serve existing results only

```sh
npm run mobile:visual:serve
```

This does not build the app or run Maestro.

### Useful options

```sh
# Do not open the browser automatically.
npm run mobile:visual:watch -- --device "iPhone 17" --no-open

# Reuse the already-installed visual app without even rebundling JavaScript.
npm run mobile:visual:capture -- --device "iPhone 17" --skip-build

# Force recreation of the isolated native project if troubleshooting its cache.
npm run mobile:visual:capture -- --device "iPhone 17" --clean-native

# Open Simulator.app while capturing.
npm run mobile:visual:watch -- --device "iPhone 17" --show-simulator

# Use another gallery port.
npm run mobile:visual:watch -- --device "iPhone 17" --port 4400
```

`--skip-build` is safe only when the installed visual app already contains the
current JavaScript bundle. Do not use it after changing application or harness
source unless another run has already rebundled and installed those changes.

Native/config changes invalidate the cache automatically. `--clean-native` is
an explicit recovery option and is not needed for ordinary React Native UI
work.

## Watch-mode behavior

Watch mode observes the UI and flow sources above, plus native build inputs:

- `mobile/app/`
- `mobile/src/`
- `mobile/assets/`
- `mobile/visual/harness/`
- `mobile/visual/metro.config.js`
- `mobile/maestro/visual/`
- `mobile/visual/scenarios.json`
- `core/src/`
- `mobile/app.config.ts`
- package manifests and `package-lock.json`
- `mobile/plugins/`
- `mobile/modules/`
- native theme tokens and launch/icon assets

Application, core, asset, harness, and Metro changes trigger a fast JavaScript
rebundle followed by installation on both simulators. Maestro-flow and manifest
changes restart the persistent Maestro sessions without an application build.
Native-input changes regenerate the iOS project and perform an Xcode build.
Test and snapshot files are ignored because they cannot change the installed UI.

The runner fingerprints watched sources before simulator preparation and again
after installing its watchers. If a file changes during the initial build or
capture, it automatically queues a new capture of the latest revision.

If several files are saved in sequence, changes are debounced. If a new save
arrives during capture, the runner:

1. Marks the current revision as obsolete.
2. Stops the active Maestro processes.
3. Rejects the partial screenshot cycle.
4. Waits briefly for the edit burst to settle.
5. Starts one capture from the newest revision.

A bundle already in progress may finish safely, but its obsolete revision is
not launched or published.

Capture flows avoid assertions against editable titles and error messages. If a
capture still fails, the portal shows the failed Maestro step immediately and
the watcher remains active, including during its first capture. Fix the problem
and save another file to retry.

## Using the gallery

Open `http://127.0.0.1:4173` while the visual server is running.

- Use search and the state filters to narrow the catalog.
- Each card keeps the full screenshot visible inside its simulator frame, with
  scenario information in a separate nearby panel.
- Click a screenshot for a larger inspection view. Click outside it or press
  Escape to close it.
- The status indicator changes while a recapture is running and reports
  failures without discarding the last complete catalog.
- After a successful watch capture, the browser refreshes the screenshots
  automatically.
- The Maestro HTML report link appears after a one-shot capture only. Persistent
  watch mode does not generate that report and therefore does not show a stale
  link.

The normal capture command starts the gallery server after publishing.
`npm run visual:serve` serves the most recently published catalog without
taking new screenshots.

## Add a screenshot to an existing flow

This is the normal extension path.

### 1. Reach a deterministic state

Add navigation and interactions to the appropriate file under
`maestro/visual/`. Prefer semantic text and existing accessibility labels over
coordinates.

Use state-based waits rather than fixed sleeps:

```yaml
- extendedWaitUntil:
    visible: "Expected screen title"
    timeout: 10000
```

### 2. Capture and notify watch mode

Every screenshot needs both commands:

```yaml
- takeScreenshot: example-state
- runScript:
    file: capture-screenshot.js
    env:
      SCREENSHOT: example-state.png
```

`takeScreenshot` creates the Maestro artifact. The following script notifies
the local completion bridge used by persistent watch mode. Omitting either
command breaks one of the execution modes.

### 3. Register gallery metadata

Add a matching entry to `visual/scenarios.json`:

```json
{
  "id": "example-state",
  "title": "Example state",
  "description": "What this state is intended to verify.",
  "group": "Onboarding",
  "screenshot": "example-state.png"
}
```

The `screenshot` value must exactly match the PNG passed to the completion
script.

### 4. Verify the complete catalog

```sh
npm run mobile:check
npm -w @vesta/mobile run lint
npm run mobile:visual:capture -- --device "iPhone 17"
```

Open the gallery and inspect the actual pixels. A passing selector only proves
that Maestro found the expected element; it does not prove that surrounding
navigation, sheet presentation, safe areas, or dimming are visually correct.

## Add deterministic mock data

Add a fixture when a production screen depends on live APIs, device services,
persistent state, nondeterministic timing, or unavailable credentials.

### 1. Mock the infrastructure boundary

Create a module under `visual/harness/` with the same public contract as the
production module. It may import production types, but it must not import a
visual component into production code.

Example:

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

Add the production import and fixture path to the map in
`visual/metro.config.js`:

```js
[
  "@/profile/profile-store",
  path.resolve(__dirname, "harness/profile-store.ts"),
],
```

If production code imports the same module through both an alias and a relative
path, the resolver must cover both forms. Do not change production imports just
to make the capture harness easier to wire.

### 3. Model useful transitions

Fixtures should be deterministic but may still model time and state:

- Return a fixed list for a populated screen.
- Throw a fixed error for a recovery state.
- Use a short delay when the screenshot needs a visible loading state.
- Keep small module or provider state when a Maestro action must transition the
  view from one state to another.

Avoid mocking the screen component itself. If a screen is too coupled to mock
at an infrastructure boundary, refactor production toward ordinary provider,
controller, and presentation boundaries that improve the real app as well.
Do not add a capture-only controller.

## Add another top-level flow

The current persistent design intentionally pairs two manifest flows with two
simulators. Add new screenshots to one of the existing flows whenever possible.

Do not add a third entry to the `flows` array in `visual/scenarios.json` without
first extending `startContinuousMaestro` in `scripts/visual-catalog.mjs` to
assign multiple flows to a simulator or provision another shard. Standard
Maestro sharding can distribute more flows, but the persistent local watcher
currently starts one continuous process per flow and pairs it with a simulator
by index.

Good reasons for a new top-level flow include:

- The state requires a fundamentally different clean launch.
- The flow would otherwise depend on the result of another flow.
- The new scenario group needs its own app process or permission setup.

When adding a flow, keep flows independent. No flow should depend on another
simulator having run first.

## Selector and scenario guidelines

- Prefer visible text or meaningful accessibility labels.
- Use regular expressions only when dynamic copy requires them.
- Use coordinates only for controls that cannot expose a stable semantic target.
- Wait for the exact state being captured before taking the screenshot.
- Keep dates, gateway names, and error messages fixed in fixtures.
- Use unique screenshot names across all flows.
- Capture meaningful UI states, not every intermediate animation frame.
- Keep each scenario understandable from its title and description alone.
- Use a fresh launch when native modal history could contaminate the state.

Adding a useful accessibility label to production can be a legitimate product
improvement. Adding a label whose only meaning is “the screenshot bot needs
this” violates the boundary.

## Troubleshooting

### The visual app is not installed

Run without `--skip-build`:

```sh
npm run mobile:visual:capture -- --device "iPhone 17"
```

### Java or Maestro is missing

Install Java 17 or newer and Maestro:

```sh
brew tap mobile-dev-inc/tap
brew install mobile-dev-inc/tap/maestro
```

### Native changes do not appear

Regenerate the isolated native cache:

```sh
npm run mobile:visual:capture -- --device "iPhone 17" --clean-native
```

### A flow times out

Inspect:

```text
mobile/.visual/maestro/report.html
mobile/.visual/maestro/**/screenshots/
mobile/.visual/maestro/**/screen-hierarchy/
mobile/.visual/maestro/**/logs/
```

The failure screenshot and accessibility hierarchy usually show whether the
app is on the wrong route, behind a system dialog, or waiting for different
copy.

### The portal shows a capture error

Watch mode remains alive after a flow or bundle failure. Fix the error and save
again. Restart watch mode only if the persistent Maestro or simulator process
itself is unhealthy.

### A modal screen appears inside another sheet

Treat this as a navigation-state problem, not a styling problem. Verify that:

- The base screen starts from a clean process.
- A previous native sheet was actually dismissed.
- The harness is not replacing or pushing production routes.
- Independent visual states use independent launches.

The visual harness should control data, not reimplement the production router.

### The localhost port is busy

Stop the old catalog process or use another port:

```sh
npm run mobile:visual:watch -- --device "iPhone 17" --port 4400
```

### A new iOS Simulator asks to open the deep link

The flows include an optional handler for iOS's “Open in Vesta Dev?” prompt.
If a new iOS version changes that system copy, update the system-dialog selector
in both flows rather than adding logic to the mobile app.

## Current catalog scope

The initial catalog covers disconnected onboarding, privacy, connection, and
recent-gateway states. Authenticated screens can use the same system as their
provider and controller boundaries become deterministic enough to fixture.

The same rule continues to apply as coverage grows: render real production
views, mock infrastructure outside the application, and let Maestro exercise
the public UI.
