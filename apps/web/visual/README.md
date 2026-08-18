# Web visual runner

Runner details for the web family. The system, the gallery, and the registry contract are documented in `../../visual/README.md`.

## How a capture runs

The untouched app renders at its real route on the plain vite dev server (`HTTPS=false`, port 1430). Determinism is injected at the network boundary by Playwright:

- `harness/storage.ts` seeds the connection and the theme in `localStorage`.
- `harness/sync-fixtures.ts` answers the `/sync` WebSocket with typed fixture frames.
- `harness/http-fixtures.ts` routes the HTTP paths the flow touches.
- `harness/native-stub.ts` defines `window.vestaNative` for the `desktop` platforms, so the app takes its real desktop path (`.desktop`, `.vibrancy`, the title-bar inset). Every method is inert.

`capture.spec.ts` loads `scenarios.json` through `@vesta/visual/registry`, runs one test per scenario, and writes each shot into the store with `putShot`.

## Projects

One Playwright project per web platform, named by its id: `web` and `web-dark` at 1280x800, `desktop` and `desktop-dark` at 1200x750 with the native stub, `web-narrow` and `web-narrow-dark` at 420x900. `colorScheme` follows the platform's theme so OS-scheme surfaces (the toaster) match the page.

## Commands

From `apps/`:

```sh
npm run web:visual:capture                          # all six platforms
npm run web:visual:capture -- --project desktop-dark
npm run web:visual:capture -- --workers=2           # what a gentle scan passes
```

Install the browser once: `npx playwright install chromium` in `apps/web`. The HTML report is written to `apps/web/.visual/report/`; the gallery links it as "Web report".

## Boundary

Nothing under `src/` changes for capture. No scenario flags, no capture env checks, no bot-only test ids. Selectors are visible text and roles. Every scenario waits on a `settle` assertion, never a bare sleep.

## Add a scenario

1. Add the entry to `scenarios.json`: `id`, `title`, `description`, `group`, plus the state the fixtures need (`route`, `agentStatus`, `createResponse`, `deltas`, `hang`, `agentName`, `provider`).
2. Add `drive` and `settle` under the same id in `drives.ts`.
3. Extend `http-fixtures.ts` or `sync-fixtures.ts` if the flow touches a new endpoint. Keep `harness/fixtures.test.ts` and `registry.test.ts` green.
4. Run one project, then the full matrix, and inspect the pixels in the gallery.
