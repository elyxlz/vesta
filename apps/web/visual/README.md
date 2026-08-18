# Web visual harness

Deterministic screenshots of production web views, the web counterpart of the mobile visual QA system. The untouched app renders at the real route on the plain vite dev server; determinism is injected at the network boundary by Playwright: storage seeds (connection, theme), a mocked `/sync` WebSocket speaking typed fixture frames, and a route table for the HTTP paths the flow touches. The fixture frames are validated by the production parser in `harness/fixtures.test.ts`, which runs inside the normal vitest suite, so protocol drift fails loudly.

## Commands

Run from `apps/`:

```sh
npm run web:visual            # capture everything, build the gallery, serve + open it
npm run web:visual:capture    # capture + build the gallery, then exit
```

One matrix cell while iterating, from `apps/web/`:

```sh
npx playwright test --config visual/playwright.config.ts --project dark-desktop
```

Output: `apps/web/.visual/web/` (gitignored), one PNG per scenario per project (`<scenario>--<project>.png`) plus `index.html`, the contact-sheet gallery. Serve an existing catalog without capturing: `node visual/gallery.mjs --serve`.

## Boundary rule

Nothing under `src/` changes for capture. No scenario flags, no capture env checks, no bot-only test ids. Selectors use visible text and existing roles; every scenario waits on a settle assertion, never a bare sleep. Production views remain the rendered implementation; only infrastructure answers are fixtures.

## Adding a scenario

1. Add an entry to `scenarios.ts`: unique kebab-case `id`, `drive(page)` walking the public UI, `settle(page)` asserting the visible state being captured. Reuse the drive helpers.
2. If the state needs different network answers, extend `harness/http-fixtures.ts` (HTTP) or pass roster deltas built with `harness/sync-fixtures.ts` helpers. Keep values fixed and visually meaningful.
3. Keep `harness/fixtures.test.ts` green; extend it when adding new frame builders.
4. Run the single-project capture, then the full matrix, and eyeball the gallery pixels, not just the pass result.
