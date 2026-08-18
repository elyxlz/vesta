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
npm run web:visual:capture -- --project web-dark
```

The web runner needs Playwright's browser once: `npx playwright install chromium` in `apps/web`.

There is no watch mode. To recapture after an edit, press Scan in the gallery or run a capture command.

## Platforms

A platform is one gallery slot: one capture target. A theme variant is its own platform, the same way the 3-button Android persona is. `platforms.mjs` is the one owner of this table.

| Id | Label | Family | Theme | Frame | Runner |
| --- | --- | --- | --- | --- | --- |
| `ios` | iOS | mobile | light | phone | `ios` |
| `android` | Android | mobile | light | android-phone | `android` |
| `android-galaxy` | Android · 3-button | mobile | light | android-phone | `android-galaxy` |
| `ios-dark` | iOS · dark | mobile | dark | phone | `ios` |
| `android-dark` | Android · dark | mobile | dark | android-phone | `android` |
| `android-galaxy-dark` | Android · 3-button · dark | mobile | dark | android-phone | `android-galaxy` |
| `web` | Web | web | light | browser | `web` |
| `desktop` | Desktop | web | light | desktop-window | `web` |
| `web-narrow` | Web · phone | web | light | phone-browser | `web` |
| `web-dark` | Web · dark | web | dark | browser | `web` |
| `desktop-dark` | Desktop · dark | web | dark | desktop-window | `web` |
| `web-narrow-dark` | Web · phone · dark | web | dark | phone-browser | `web` |

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

| Path | Owns |
| --- | --- |
| `apps/visual/platforms.mjs` | The platform, runner, and family tables |
| `apps/visual/registry.mjs` | The scenario contract: load and validate a `scenarios.json` |
| `apps/visual/store.mjs` | Shot store paths, `putShot`, the shot index, the drift warning |
| `apps/visual/run-status.mjs` | The capture phase file the gallery polls |
| `apps/visual/gallery/` | The server, the page model, the HTML, the styles, the client script |
| `apps/visual/cli.mjs` | `serve` and `capture <runner>` |
| `apps/mobile/visual/`, `apps/mobile/scripts/visual-*.mjs` | The mobile registry, fixtures, flows, and the iOS and Android runners |
| `apps/web/visual/` | The web registry, drives, fixtures, and the Playwright runner |
| `apps/visual/.visual/` | Generated, ignored: `shots/`, `run-status-<runner>.json`, `capture-<runner>.log` |

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
- An id or a screenshot name is unique across both families. The gallery composes both, so a collision would overwrite a card.

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
- Each slot draws its platform's frame: `phone`, `android-phone`, `browser`, `desktop-window`, or `phone-browser`.
- Every card has dark captures, so the Dark button flips mobile and web cards alike.
- Scan cells: one per runner, sized to their content. Scan spawns the runner; while it runs, the cell shows the runner's phase and elapsed time in place of the last-scan stamp, the count restarts from this run's shots, and the runner's slots dim as "Refreshing" until replaced. A failed run shows its error in the cell. "Gentle" runs the Maestro runners with `--gentle` and the web runner with `--workers=2`.
- Copy ref copies `visual-ref: <id> [<platform>]` plus the group, title, revision, and image URL, for pasting into a chat.
- The runner reports link under `/reports/<runner>/report.html` when they exist.
- Routes: `/`, `/shots.json`, `/status.json`, `POST /capture/<runner>?gentle=0|1`, `/gallery/*`, `/reports/<runner>/*`, and static files under the store.

## Add a scenario

Mobile:

1. Add a step to a flow in `apps/mobile/maestro/visual/`, wait on the visible state, then `takeScreenshot: <id>` (the Maestro report artifact) and the `capture-screenshot.js` callback with `SCREENSHOT: <id>.png` (what writes the shot, on both platforms).
2. Add the entry to `apps/mobile/visual/scenarios.json`.
3. Run `npm run mobile:visual:capture` and inspect the gallery.

Web:

1. Add the entry to `apps/web/visual/scenarios.json` with its state fields.
2. Add the `drive` and `settle` closures under the same id in `apps/web/visual/drives.ts`.
3. Extend `apps/web/visual/harness/` if the flow touches a new endpoint or frame.
4. Run `npm run web:visual:capture` and inspect the gallery. `registry.test.ts` fails if an id has no drive.

Details for each runner live in `apps/mobile/visual/README.md` and `apps/web/visual/README.md`.

## Troubleshooting

- The gallery says "Could not compose the gallery": read the message. It names the registry file or the invalid entry.
- A scan row says "last scan failed": read `apps/visual/.visual/capture-<runner>.log`.
- Web: `browserType.launch: Executable doesn't exist`: run `npx playwright install chromium` in `apps/web`.
- Web: port 1430 is busy: stop the other vite dev server, or the runner reuses it and captures whatever it serves.
- Web: a `settle` fails: open `apps/web/.visual/report/index.html`; that scenario keeps its previous shot.
- iOS: `xcodebuild exited with 65` after moving the checkout: run the iOS runner with `--clean-native` once. Xcode's module cache pins absolute paths.
- iOS: the visual app is not installed: run without `--skip-build`.
- Android: Java or Maestro is missing: install JDK 17 and Maestro, see the mobile README.
- A flow times out: read the first failed Maestro step in the runner report; later missing shots are downstream.
- Port 4173 is busy: stop the other gallery, or `npm run visual:serve -- --port 4180`.
