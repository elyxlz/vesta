# Visual QA unification: one harness and one gallery for every Vesta app

Date: 2026-08-18. Branch: `epic/apps` (PR #2126).

## Goal

One deterministic screenshot system covers every Vesta client: mobile (iOS, Android with gesture and 3-button navigation), web (browser, light and dark), and desktop (the web screens in the Electron window). One gallery shows every scenario across every platform. The system is a review gallery first; its shot layout leaves room for pixel baselines later.

## Today

Two harnesses exist and share nothing:

| | Mobile (`apps/mobile/visual`) | Web (`apps/web/visual`) |
|---|---|---|
| Registry | `scenarios.json`: `id`, `title`, `description`, `group`, `screenshot` | `scenarios.ts`: state plus `drive`/`settle` closures, no title or description |
| Runner | Maestro on simulators and emulators | Playwright with network mocks |
| Slot axis | platform: `ios`, `android`, `android-galaxy` | project: theme x viewport |
| Shots | `apps/mobile/.visual/shots/<platform>/<id>.png` | `apps/web/.visual/web/<id>--<project>.png` |
| Gallery | live, polling, scan buttons, port 4173 | static contact sheet, port 4174 (collides with the Android runner) |

`apps/mobile/scripts/visual-catalog.mjs` (3290 lines) is at once the iOS runner, the library the Android runner imports twenty symbols from, and the gallery. The web harness never renders the desktop path: nothing sets `window.vestaNative`.

## Decisions

1. A new workspace package `apps/visual/` (`@vesta/visual`) owns the app-agnostic parts: the platform table, the registry contract, the shot store, run status, and the gallery. Each app keeps its own capture runner and writes into the shared store.
2. Desktop is the web screens captured with a native-bridge stub, so the app takes its real desktop DOM path; the gallery paints the window chrome.
3. Every platform has a dark sibling (`ios-dark`, `android-dark`, `android-galaxy-dark`, `web-dark`, `desktop-dark`, `web-narrow-dark`). A theme variant is its own platform id, the same way `android-galaxy` is. A runner drives each scenario once and captures both themes from that drive by flipping the OS appearance in place (`simctl ui appearance`, `cmd uimode night`, Playwright `emulateMedia`), waiting for the picture to settle; there is no dark drive.
4. The web registry takes the mobile shape: `scenarios.json` for card data and state, `drives.ts` for the closures.
5. Watch mode is removed on every platform. Recapture is a Scan button or a capture command.
6. Frames are gallery CSS, never baked into a PNG.

## Layout

### `apps/visual/` (new, `@vesta/visual`, private, ESM `.mjs`, no build)

```
apps/visual/
  package.json                 scripts: serve, capture, test, lint
  cli.mjs                      main(): `serve [--port 4173] [--no-open]` | `capture <runner> [--gentle]`
  platforms.mjs                PLATFORMS, RUNNERS, FAMILIES, platformFamily(), platformsOfFamily(), runnerOf()
  registry.mjs                 loadRegistry(family), validateRegistry(), scenarioOnPlatform(), scenariosForPlatform(), excludedNote()
  store.mjs                    storeDirectory, shotsDirectory, platformShotsDirectory(), putShot(), shotEntries(), pngSize(), shotDriftWarning(), atomicWriteFile()
  run-status.mjs               publishRunStatus(), currentRunStatus(), newerRunStatus(), STALE_CAPTURE_MS
  gallery/
    server.mjs                 serveCatalog(port, shouldOpen), spawnCapture(runner, gentle), safeStaticPath()
    view.mjs                   composeGallery(), galleryView(), sectionHtml(), cardHtml(), slotHtml(), frameHtml()
    page.mjs                   galleryHtml(view): the document shell
    styles.css                 served static; Vesta palette; .frame-phone, .frame-browser, .frame-desktop-window, .frame-phone-browser
    client.js                  served static; poll loop, applyShots(), updateScanRows(), copy-ref, collapse persistence
  platforms.test.mjs  registry.test.mjs  store.test.mjs  gallery/view.test.mjs  gallery/server.test.mjs
  README.md                    the one architecture doc
  .agents/skills/visual-qa/SKILL.md + agents/openai.yaml
  .visual/                     gitignored: shots/<platform>/<id>.png, run-status-<runner>.json, capture-<runner>.log
```

`platforms.mjs` is the single owner of which platforms exist:

```js
export const PLATFORMS = {
  ios:               { label: "iOS",                family: "mobile", theme: "light", frame: "phone",          runner: "ios" },
  android:           { label: "Android",            family: "mobile", theme: "light", frame: "phone",          runner: "android" },
  "android-galaxy":  { label: "Android · 3-button", family: "mobile", theme: "light", frame: "phone",          runner: "android-galaxy" },
  web:               { label: "Web",                family: "web",    theme: "light", frame: "browser",        runner: "web" },
  desktop:           { label: "Desktop",            family: "web",    theme: "light", frame: "desktop-window", runner: "web" },
  "web-narrow":      { label: "Web · phone",        family: "web",    theme: "light", frame: "phone-browser",  runner: "web" },
  "web-dark":        { label: "Web · dark",         family: "web",    theme: "dark",  frame: "browser",        runner: "web" },
  "desktop-dark":    { label: "Desktop · dark",     family: "web",    theme: "dark",  frame: "desktop-window", runner: "web" },
  "web-narrow-dark": { label: "Web · phone · dark", family: "web",    theme: "dark",  frame: "phone-browser",  runner: "web" },
};
export const RUNNERS = {   // a Scan button spawns `npm -w <workspace> run <script> -- [...args] [--gentle]`
  ios:              { label: "iOS",                workspace: "@vesta/mobile", script: "visual:ios:capture" },
  android:          { label: "Android",            workspace: "@vesta/mobile", script: "visual:android:capture" },
  "android-galaxy": { label: "Android · 3-button", workspace: "@vesta/mobile", script: "visual:android:capture", args: ["--variant", "android-galaxy"] },
  web:              { label: "Web",                workspace: "@vesta/web",    script: "visual:capture" },
};
export const FAMILIES = {  // registry path per family, relative to apps/
  mobile: { label: "Mobile", registry: "mobile/visual/scenarios.json" },
  web:    { label: "Web",    registry: "web/visual/scenarios.json" },
};
```

`platformFamily(id)` replaces the `platform.startsWith("android")` test. Runner-only facts stay in the runner keyed by platform id: the Android AVD name and nav overlay in `visual-android.mjs`, the Playwright viewport and stub in `playwright.config.ts`.

### `apps/mobile/scripts/` (runners only)

```
visual-runner.mjs      mobile-shared: run(), gentleSpawnPlan(), setGentleMode(), activeShardCount(), assertHarnessBoundary(),
                       nativeInputFingerprint(), jsInputFingerprint(), jsBundleCurrent(), recordJsBundle(),
                       flowFailureError(), maestroFlowSummary(), createMaestroFailureParser(), createInactivityWatchdog(), exists(), filesBelow()
visual-ios.mjs         was visual-catalog.mjs: iOS build, simulators, two shards, Maestro; imports @vesta/visual for store, registry, run status
visual-android.mjs     was visual-catalog-android.mjs: emulator, variants keyed by platform id, stageMaestroShots() -> putShot()
visual-runner.test.mjs  visual-ios.test.mjs  visual-android.test.mjs
```

Deleted from the iOS runner: the `watch` command and everything only it used (debounce, obsolete-run cancellation, `assignFlowsToShards`, `continuousShardFlow`, `shouldIgnoreWatchPath`, the continuous per-shard Maestro processes). The bridge env var `WATCH_CAPTURE_URL` becomes `CAPTURE_URL` (`maestro/visual/capture-screenshot.js`). `apps/mobile/.visual/` keeps the native and bundle caches; only `shots/` leaves.

### `apps/web/visual/` (the web runner)

```
scenarios.json                 24 entries: id, title, description, group, plus state (route, agentStatus, createResponse, deltas, hang, provider, agentName)
drives.ts                      export const DRIVES: Record<string, { drive(page), settle(page) }>
capture.spec.ts                iterates loadRegistry("web"); one test per scenario; screenshot to a temp path, then putShot(project.name, `${id}.png`)
playwright.config.ts           six projects named by platform id; viewports web 1280x800, desktop 1200x750, narrow 420x900; colorScheme from PLATFORMS[id].theme
harness/native-stub.ts         installNativeStub(page): addInitScript defining window.vestaNative (platform "darwin") per VestaNativeApi
harness/http-fixtures.ts, sync-fixtures.ts, storage.ts, fixtures.test.ts     unchanged
registry.test.ts               every scenarios.json id has a DRIVES entry and vice versa
DELETED: gallery.mjs, test-options.ts, global-setup.ts
```

`desktop` and `desktop-dark` run `installNativeStub` before `seedStorage`, so the app takes its real desktop path (`.desktop`, `.vibrancy`, `data-platform="macos"`, title-bar inset). The stub implements the `VestaNativeApi` contract in `apps/web/src/lib/native/types.ts` with inert functions and a memory-backed store. A `settle` failure fails that test only; the store keeps every other shot.

### Wiring

- `apps/package.json`: `visual` (serve and open), `visual:serve`, `visual:capture -- <runner>`. `mobile:visual:capture`, `mobile:visual:android:capture`, `web:visual:capture` stay as the runner commands the umbrella spawns. Every other `mobile:visual*` and `web:visual*` script is removed (the capture-and-serve, serve-only, and watch forms), because serving lives only in the umbrella.
- `apps/.gitignore`: `visual/.visual/`, `mobile/.visual/`, `web/.visual/`. The root `.gitignore` entry for `apps/web/.visual/` moves here.
- `check.sh`: new `app-visual` (eslint plus vitest for `@vesta/visual`), chained into `web`; a matching `test-app-visual` CI job gated on nothing but its own paths.
- `.claude/skills/visual-qa/SKILL.md` points at `apps/visual/.agents/skills/visual-qa/SKILL.md`. Both `mobile-visual-qa` directories are deleted.
- The `product-critique` workflow's reference to `tools/critique/capture-ui.mjs` (a file that never existed) points at `npm run visual:capture`.

## Registry contract

Both `scenarios.json` files validate against one contract in `registry.mjs`:

```
{ version: 1,
  flows?: string[],                    // mobile only: Maestro flow files, order is shard order
  scenarios: [{ id, title, description, group, screenshot?, platforms?, ...familyState }] }
```

- `screenshot` defaults to `<id>.png`. Existing mobile entries that spell it out keep working.
- `platforms` restricts within the family. `validateRegistry` rejects an id outside `platformsOfFamily(family)`. An uncaptured slot shows "Not captured yet"; an excluded slot shows `excludedNote()` ("iOS only", "Web + Desktop only").
- Web state fields ride in the same object; the loader passes them through and `capture.spec.ts` types them at the boundary.
- Duplicate ids and duplicate screenshot names are rejected across both registries, because the gallery composes both and a collision would overwrite a card.

## Store

`apps/visual/.visual/shots/<platform>/<screenshot>.png`, one directory per platform id. `putShot(platform, name, sourcePath)` is the only writer: copy to `<name>.tmp-<pid>`, then `rename`, so the polling gallery never reads a torn PNG. Today's Android staging becomes this one owner; iOS `simctl` output and Playwright screenshots route through it too. `shotDriftWarning()` compares a runner's produced set to `scenariosForPlatform()` and warns; it never fails a run. `run-status-<runner>.json` and `capture-<runner>.log` sit beside `shots/`.

Existing shots migrate once: `mv apps/mobile/.visual/shots/* apps/visual/.visual/shots/`. No recapture.

## Gallery

- One server, port 4173, bound to `127.0.0.1`. Routes: `/`, `/shots.json`, `/status.json`, `POST /capture/<runner>`, static files under the store. The web `gallery.mjs` and the Android runner's `serve` command are deleted; `serve` lives only in the umbrella.
- Title: "Vesta Apps QA". Status copy names the runner ("Capturing Web…"), never simulators or shards.
- Sections: `<family label> · <group>` ("Mobile · Onboarding", "Web · Onboarding"), in registry order, mobile first. Collapsible, persisted in `localStorage`.
- Card: one scenario. Slots: `platformsOfFamily(family)` minus its `platforms` exclusions, in `PLATFORMS` order, shown one theme at a time. Every slot carries `data-theme` and every card `data-themes`; a Dark toggle in the scan bar sets `body[data-theme]` and CSS hides the off-theme slots, so a card that has dark captures flips to them and a mobile card stays. The choice persists in `localStorage`. The view has no theme logic beyond the tags.
- Frames: `frameHtml(frame)` draws chrome around the shot from the Vesta palette in `styles.css`. `phone`: the rounded dark box at shot ratio (today's `.device-screen`). `browser`: a tab strip (three dots and an address pill). `desktop-window`: a macOS title bar with traffic lights at the app's `hiddenInset` offset. `phone-browser`: the phone box with a slim address bar.
- Scan rows: one per `RUNNERS` entry (iOS, Android, Android · 3-button, Web). The Web row fills all six web platforms in one Playwright run. The Gentle checkbox applies to every runner; for web it maps to `--workers=2`.
- Copy-ref keeps its shape: `visual-ref: <id> [<platform>]`, `group`, `rev`, `image`.

## Web runner details

- Six projects, each named by platform id. Each seeds `theme` in storage and sets Playwright `colorScheme` from `PLATFORMS[id].theme`, so surfaces that follow the OS scheme (the toaster) match the page.
- `web` and `web-dark`: 1280x800. `desktop` and `desktop-dark`: 1200x750 (the Electron `WINDOW_WIDTH`/`WINDOW_HEIGHT`) with the native stub. `web-narrow` and `web-narrow-dark`: 420x900.
- The runner README gains `npx playwright install chromium`.

## Rewording

Everything that names the system as mobile becomes app-wide: skill `mobile-visual-qa` becomes `visual-qa`; `apps/visual/README.md` owns architecture, commands, the boundary rule, add-a-scenario, and troubleshooting; `apps/mobile/visual/README.md` and `apps/web/visual/README.md` shrink to runner mechanics and point up. Gallery strings drop "Mobile", "simulator shards", and "watch".

## Tests

- `@vesta/visual`: `platforms.test.mjs` (every platform has a family and a runner, every runner has at least one platform, ids are unique), `registry.test.mjs` (contract, `screenshot` default, cross-registry collisions, exclusions), `store.test.mjs` (`putShot` atomicity, `shotEntries`, drift), `gallery/view.test.mjs` (moved from mobile: sections, slots, one frame per platform, mixed families, wrap), `gallery/server.test.mjs` (moved: `safeStaticPath`, capture spawn table).
- Mobile: runner tests move with their functions; `visual-android.test.mjs` keeps `stageMaestroShots` through `putShot`.
- Web: `registry.test.ts` (ids and drives match one to one), `fixtures.test.ts` unchanged.
- Before handoff: `./check.sh app-visual app-mobile app-web`; one full iOS capture, one Android capture, one web capture; then eyeball the gallery, nine platform slots each in its frame.

## Out of scope

CI capture, pixel diffing and baselines (the store key `<platform>/<id>.png` is stable for it), watch mode on any platform, real Electron capture, mobile-web scenarios beyond the responsive SPA.
