# Web visual runner

Runner details for the web family. The system, the gallery, and the registry contract are documented in `../../visual/README.md`.

## How a capture runs

The untouched app renders at its real route on the plain vite dev server (`HTTPS=false`, port 1430). Determinism is injected at the network boundary by Playwright:

- `harness/storage.ts` seeds the connection and the `system` theme in `localStorage`.
- `harness/sync-fixtures.ts` answers the `/sync` WebSocket with typed fixture frames.
- `harness/http-fixtures.ts` routes the HTTP paths the flow touches.
- `harness/native-stub.ts` defines `window.vestaNative` for the `desktop` platforms, so the app takes its real desktop path (`.desktop`, `.vibrancy`, the title-bar inset). Every method is inert.

`capture.spec.ts` loads `scenarios.json` through `@vesta/visual/registry`, runs one test per scenario, and writes each shot into the store with `putShot`.

## Projects

One Playwright project per light web platform, named by its id: `web` at 1280x800, `desktop` at 1200x750 with the native stub, `web-narrow` at 420x900. Each test drives the scenario once: it takes the light shot, then flips the emulated color scheme to dark (`page.emulateMedia`), waits for `html.dark`, and takes the dark shot under the sibling platform (`web-dark`, `desktop-dark`, `web-narrow-dark`). The seeded theme is `system`, so the app and every OS-scheme surface (the toaster) follow the flip.

## Commands

From `apps/`:

```sh
npm run web:visual:capture                          # all six platforms, three drives
npm run web:visual:capture -- --project desktop      # desktop and desktop-dark
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
