# Vesta visual QA

One deterministic screenshot system covers every Vesta client: mobile (iOS, Android with gesture and 3-button navigation), web (browser, light and dark), and desktop (the web screens in the Electron window). One gallery shows every scenario on every platform. The system is local only: no CI job captures pixels.

Each app owns its capture runner. `@vesta/visual` (this package) owns the parts that are the same for every app: the platform table, the registry contract, the shot store, run status, and the gallery.

## Quick start

Run every command from `apps/`.

```sh
# Serve the gallery at http://127.0.0.1:4173 and open it.
npm run visual

# Serve without opening a browser.
npm run visual:serve

# Capture one runner from the terminal instead of the gallery's Scan button.
npm run visual:capture -- ios
npm run visual:capture -- android
npm run visual:capture -- android-galaxy
npm run visual:capture -- web
npm run visual:capture -- web --gentle

# Or call a runner directly with its own options.
npm run mobile:visual:capture -- --device "iPhone 17"
npm run mobile:visual:android:capture -- --variant android-galaxy
npm run web:visual:capture -- --project desktop   # a light project; its dark sibling is captured in the same drive
```

The web runner needs Playwright's browser once: `npx playwright install chromium` in `apps/web`.

There is no watch mode. To recapture after an edit, press Scan in the gallery or run a capture command.

## Page references while coding

The default suite is **all**: page destinations plus detailed error and interaction states, including voice conversation. Page captures cover destinations rather than feature checklists: adding or removing a card should require no capture-flow edit. Use **pages** or **states** only when narrowing coverage.

```sh
npm run visual:capture -- web --page settings
npm run visual:capture -- ios --page settings --gentle
node visual/cli.mjs refs --page settings --platform web
node visual/cli.mjs compare web --page settings
npm run visual:capture -- ios --page agent-chat-conversation
npm run visual:capture -- web --suite states  # only detailed states
```

`refs` prints JSON containing absolute image paths, timestamps, capture completeness, gallery anchors, and a refresh command. Agents can open those paths directly with their image viewer. Freshness is explicitly unchecked in this lightweight index: run the refresh command first when current pixels matter; unchanged inputs skip automatically. Humans can search pages in the gallery, click a page title for its stable link, refresh one page, or copy its local image references.

Long pages are captured as overlapping viewports (`page-settings.png`, `page-settings--02.png`, and so on), discovered by scrolling rather than looking for a named last card. The lightbox's Previous/Next controls and the JSON `images` array expose every section. Native scrolling ends when another swipe produces the same stable image; web scrolling follows the largest visible scroll surface to its end. Both fail at 24 viewports instead of silently truncating. Chat, live logs, and editors capture their useful visible state: sweeping an editor can focus its input and type on the keyboard instead of scrolling. Native wall time is fixed while timers still run.

Capture, refs, comparison, baseline commands, and the gallery include both suites by default. Use `--suite pages|states|all` and `--page <key-or-id>` to narrow selection. Direct runner commands use `VISUAL_SUITE` and `VISUAL_PAGE`. Gallery links accept `?suite=states` or `?page=settings`. `--all` means force recapture of the selected suite; it does not change selection.

## Platforms

A platform is one gallery slot: one capture target. A theme variant is its own platform, the same way the 3-button Android persona is. `platforms.mjs` is the one owner of this table.

| Id                    | Label                     | Family | Theme | Frame          | Runner           |
| --------------------- | ------------------------- | ------ | ----- | -------------- | ---------------- |
| `ios`                 | iOS                       | mobile | light | phone          | `ios`            |
| `android`             | Android                   | mobile | light | pixel          | `android`        |
| `android-galaxy`      | Android · 3-button        | mobile | light | galaxy         | `android-galaxy` |
| `ios-dark`            | iOS · dark                | mobile | dark  | phone          | `ios`            |
| `android-dark`        | Android · dark            | mobile | dark  | pixel          | `android`        |
| `android-galaxy-dark` | Android · 3-button · dark | mobile | dark  | galaxy         | `android-galaxy` |
| `web`                 | Web                       | web    | light | browser        | `web`            |
| `desktop`             | Desktop                   | web    | light | desktop-window | `web`            |
| `web-narrow`          | Web · phone               | web    | light | phone-browser  | `web`            |
| `web-dark`            | Web · dark                | web    | dark  | browser        | `web`            |
| `desktop-dark`        | Desktop · dark            | web    | dark  | desktop-window | `web`            |
| `web-narrow-dark`     | Web · phone · dark        | web    | dark  | phone-browser  | `web`            |

A runner is what a Scan button spawns: `npm -w <workspace> run <script>`. Every runner drives each scenario once and captures both themes from that one drive: it takes the light shot, flips the OS appearance (`simctl ui appearance`, `cmd uimode night`, or Playwright's emulated color scheme, all of which the apps follow), waits for the picture to settle, takes the dark shot under the sibling platform, and flips back. `themedSibling(platform, theme)` in `platforms.mjs` names the pair: same runner, same frame, other theme.

## Architecture

```text
apps/mobile/visual + scripts/visual-*.mjs     apps/web/visual
   Maestro on simulators and emulators          Playwright with network mocks
                 |                                        |
                 +----------- putShot(platform, id.png) --+
                                      |
                                      v
              apps/visual/.visual/shots/<platform>/<id>.png   (the store)
                                      |
                                      v
   gallery: both registries + the store, composed per request, port 4173
```

| Path                                                      | Owns                                                                                                                         |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `apps/visual/platforms.mjs`                               | The platform, runner, and family tables                                                                                      |
| `apps/visual/registry.mjs`                                | The scenario contract: load and validate a `scenarios.json`                                                                  |
| `apps/visual/store.mjs`                                   | Shot store paths, `putShot`, the freshness record beside each shot, the shot index, the drift warning                        |
| `apps/visual/fingerprint.mjs`                             | The fingerprint over a shot's source files and inputs, and the `--all` / `VISUAL_CAPTURE_ALL` switch                         |
| `apps/visual/stability.mjs`                               | The shared pixel-stability check for every runner                                                                            |
| `apps/visual/comparison.mjs`                              | Baselines, pixel diffs, and approval of reviewed captures                                                                    |
| `apps/visual/run-status.mjs`                              | The capture phase file the gallery polls                                                                                     |
| `apps/visual/gallery/`                                    | The server, the page model, the HTML, the styles, the client script                                                          |
| `apps/visual/cli.mjs`                                     | `serve`, `capture <runner>`, `baseline [platform]`, and `compare [platform]`                                                 |
| `apps/mobile/visual/`, `apps/mobile/scripts/visual-*.mjs` | The mobile registry, fixtures, flows, and the iOS and Android runners                                                        |
| `apps/web/visual/`                                        | The web registry, drives, fixtures, and the Playwright runner                                                                |
| `apps/visual/.visual/`                                    | Generated, ignored: `shots/` (each `<id>.png` with its `<id>.fp` record), `run-status-<runner>.json`, `capture-<runner>.log` |

## Freshness

A scan retakes a shot only when something it depends on changed since it was taken. Beside every light shot the store keeps `<id>.fp`: the fingerprint of the shot's inputs and the list of source files it covers. A runner recomputes the fingerprint over those files' current contents plus the scenario's own inputs and skips the shot when it matches and both themes exist.

- **Web**: the source set is what the page executed during the capture, from Playwright's JS coverage. Vite serves modules unbundled, so each coverage entry names a file; a module counts when one of its functions ran (a component rendered, a helper was called), which is what separates screens, since the router loads every page module at startup. Vite's Fast Refresh plumbing is ignored. Always-on inputs: the harness, `capture.spec.ts`, `playwright.config.ts`, `index.html`, `vite.config.ts`, the global CSS, the lockfile, the scenario's drives file, and its card (`apps/web/visual/freshness-inputs.mjs`).
- **Mobile**: the unit is a flow file, and its source set is the transitive import closure, in Metro's own dependency graph for the platform (built with the visual Metro config, so aliases, platform variants, and the harness substitutions resolve as in the bundle), of the route files the flow deep-links into plus every `_layout.tsx` on the way (`apps/mobile/scripts/visual-sources.mjs`). Always-on inputs: the flow text, `capture-screenshot.js`, the runner scripts, the native input fingerprint, and the flow's cards. A flow is skipped when every shot it takes on the platform is fresh.
- `plan` (`node scripts/visual-ios.mjs plan`, `node scripts/visual-android.mjs plan --variant <v>`, `node visual/plan.mjs` in web) prints the decision as JSON without capturing; the gallery's Scan dialog shows it.
- `--all` on a runner, or the dialog's "Everything", retakes every shot; `VISUAL_CAPTURE_ALL=1` is the carrier.

A change under the app that the screen does not reach does not retake it; a change the static or runtime view cannot see (a dynamic `require`, a value read through a global) is the one blind spot, and "Everything" covers it.

Planning hashes each source file once per plan, sharing the result across scenarios and projects. The next plan starts with an empty cache. Replacing a light shot invalidates its previous freshness record until both themes finish, so a failed forced capture is retried on the next scan.

## Pixel regressions

Capture and comparison are separate: a UI change should produce a screenshot to review. Scenarios declare fixture state and navigation actions, without final assertions about component presence, exact copy, disabled controls, or internal markup. The shared capture check requires identical frames for at least 250 ms within an eight-second budget. Mobile waits for a visual-only boot-handoff signal after every deep link, so a blank native startup surface cannot be mistaken for the destination. Web also waits for fonts and pending one-shot timers of up to two seconds, which covers startup holds and debounces without waiting for long refresh timers or intervals. Missing navigation targets and unstable screens remain capture failures with diagnostic screenshots; they never approve a baseline.

From `apps/`:

```sh
node visual/cli.mjs baseline          # Explicitly seed missing baselines from existing captures
node visual/cli.mjs compare web       # Compare page references on web/light
node visual/cli.mjs compare           # Compare pages across platforms, including dark variants
```

Baselines live under `visual/.visual/baselines/<platform>/`. The seed command never replaces an existing baseline. Capture writes only current shots. `compare` emits JSON and exits 1 for changed, resized, new, or missing shots. Pixelmatch uses a 0.1 per-pixel color threshold and ignores antialiasing noise; any remaining changed pixel is reported, and dimensions are compared without resizing either image.

Click **Review** on a gallery slot for baseline, current, and highlighted diff images. Choose a page section to inspect it. **Approve entire page** explicitly accepts every section, including added or removed viewports. Incomplete captures cannot be approved. The images being reviewed are immutable content-addressed files, and approval refuses if a newer capture arrived since the review opened. New scenarios have no baseline until approved. Comparison results and review images are cached locally under `.visual/comparisons/` and `.visual/review-images/`; no PNGs are committed or captured in CI.

## Registry contract

Each family has one `scenarios.json` (`apps/mobile/visual/scenarios.json`, `apps/web/visual/scenarios.json`). Both validate against the same contract:

```json
{
  "version": 1,
  "flows": ["maestro/visual/connect.yml"],
  "scenarios": [
    {
      "id": "agent-chat",
      "title": "Agent conversation",
      "description": "The chat with a few messages exchanged.",
      "group": "Agent",
      "screenshot": "agent-chat.png",
      "platforms": ["ios"]
    }
  ]
}
```

- `id`, `title`, `description`, and `group` are required. The gallery reads them.
- `screenshot` defaults to `<id>.png`.
- `platforms` restricts a scenario to some platforms of its family. An absent slot shows "Not captured yet"; an excluded slot shows "iOS only".
- `flows` and `appId` are mobile only: the Maestro flow files, in shard order.
- Web entries carry their runner state in the same object (`route`, `agentStatus`, `createResponse`, `deltas`, `hang`, `agentName`, `provider`). The web runner reads them; the gallery ignores them.
- `page` is a stable destination key and requires `route`; it puts the scenario in the pages category. Both pages and states are included by default. Web uses `scroll: "page"` for automatic viewport coverage; mobile page flows call `capture-page.yml`.
- Ids and screenshot names are unique within each family. The same destination can share a page id across families because the store is platform-keyed and gallery anchors include the family.

## Production boundary

The runners render the production routes and screens. Only infrastructure inputs are mocked: storage, sockets, HTTP, and native services, through each runner's `harness/`.

Never add to `app/`, `src/`, or checked-in native code:

- Capture flags or screenshot environment checks
- Routes, controllers, or rendering branches that exist only for a screenshot
- Imports from `visual/` or `maestro/`
- Fake screen copies or alternate visual components
- Accessibility labels or test ids that mean something only to the screenshot bot

Frames (the phone bezel, the browser tab bar, the desktop title bar) are gallery CSS. They are never baked into a PNG, so every shot in the store is the raw screen.

## Gallery

- Sections are `<Family> · <Group>`, for example "Mobile · Onboarding" and "Web · Onboarding", in registry order, mobile first. Click a header to collapse it; the choice persists.
- A card is one scenario. Its slots are its family's platforms, shown one theme at a time: light by default. The Dark button in the scan bar flips every card to its dark platforms; the choice persists.
- Each slot draws its platform's frame: `phone` (iPhone), `pixel`, `galaxy`, `browser`, `desktop-window`, or `phone-browser`.
- Every card has dark captures, so the Dark button flips mobile and web cards alike.
- Scan cells: one per runner, sized to their content. While a runner runs, its cell shows the phase and elapsed time in place of the last-scan stamp, the count restarts from this run's shots, and the runner's slots dim as "Refreshing" until replaced. A failed run shows its error in the cell.
- Scan…: one button opens the plan dialog, which asks every runner what a scan would retake (`/plan.json`) and lists it per platform: the stale flows or scenarios, with their shots and projects. Check the platforms to run and Start; "Everything" retakes every shot instead. "Gentle" runs the Maestro runners with `--gentle` and the web runner with `--workers=2`.
- Copy ref includes the local image paths for every page section, plus the group, title, revision, and image URL.
- The live index is scoped to the selected suite and page. Polls never overlap and slow down while idle or hidden.
- The runner reports link under `/reports/<runner>/<reportFile>` (Maestro's `report.html`, Playwright's `index.html`) when they exist.
- Routes: `/`, `/shots.json`, `/status.json`, `/plan.json?all=0|1`, `POST /capture/<runner>?gentle=0|1&all=0|1`, `/gallery/*`, `/reports/<runner>/*`, and static files under the store.

## Add a scenario

Mobile:

1. Add navigation to a flow in `apps/mobile/maestro/visual/`, then `takeScreenshot: <id>` (the Maestro report artifact) and the `capture-screenshot.js` callback with `SCREENSHOT: <id>.png` (what writes the stable shot, on both platforms). Keep selector waits only when a following interaction needs them.
2. Add the entry to `apps/mobile/visual/scenarios.json`.
3. Run `npm run mobile:visual:capture` and inspect the gallery.

Web:

1. Add the entry to `apps/web/visual/scenarios.json` with its state fields.
2. Add the fixture `state` and `drive` under the same id in `apps/web/visual/drives/`. Stability and pixel comparisons belong to the shared runner.
3. Extend `apps/web/visual/harness/` if the flow touches a new endpoint or frame.
4. Run `npm run web:visual:capture` and inspect the gallery. `registry.test.ts` fails if an id has no drive.

Details for each runner live in `apps/mobile/visual/README.md` and `apps/web/visual/README.md`.

## Troubleshooting

- The gallery says "Could not compose the gallery": read the message. It names the registry file or the invalid entry.
- A scan row says "last scan failed": read `apps/visual/.visual/capture-<runner>.log`.
- Web: `browserType.launch: Executable doesn't exist`: run `npx playwright install chromium` in `apps/web`.
- Web: port 1431 is busy: stop the capture using it and retry. The runner starts its own loopback-only Vite server and refuses to reuse an existing server, so another checkout or a normal dev session cannot supply its pixels.
- Web: navigation or stability fails: open `apps/web/.visual/report/index.html` for the diagnostic screenshot and retained trace. Successful earlier shots remain available, and an incomplete theme pair is retried on the next scan.
- iOS: `xcodebuild exited with 65` after moving the checkout: run the iOS runner with `--clean-native` once. Xcode's module cache pins absolute paths.
- iOS: the visual app is not installed: run without `--skip-build`.
- Android: Java or Maestro is missing: install JDK 17 and Maestro, see the mobile README.
- A flow times out: read the first failed Maestro step in the runner report; later missing shots are downstream.
- Port 4173 is busy: stop the other gallery, or `npm run visual:serve -- --port 4180`.
