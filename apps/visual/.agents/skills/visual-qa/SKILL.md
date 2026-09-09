---
name: visual-qa
description: Capture, inspect, and extend page-based visual references for the mobile, web, and desktop clients. Use when reviewing UI changes against real screenshots or maintaining the local visual QA harness.
---

# Visual QA

Work from `apps/`. The maintained system guide is [visual/README.md](../../../README.md). Read it before changing capture mechanics; read the affected family's `mobile/visual/README.md` or `web/visual/README.md` when working on that runner.

## Reference real pages while coding

Default captures include page destinations and detailed interaction/error states. Page captures are not feature checklists: adding or removing a settings card should not need a flow edit.

```sh
npm run visual:capture -- web --page settings
node visual/cli.mjs refs --page settings --platform web
npm run visual
node visual/cli.mjs compare web --page settings
```

Use a page key from `refs` for chat, home, dashboard, connection, sign-in, settings sections, or other destinations. Runner choices are `web`, `ios`, `android`, and `android-galaxy`. Web captures browser, desktop-window, and narrow layouts; each runner captures light and dark from one navigation.

The JSON index gives absolute image paths, timestamps, completeness, refresh commands, and gallery anchors. Open the actual images, including every entry in `images`. It does not claim current source freshness: refresh first when current pixels matter. The runner skips unchanged inputs.

The gallery defaults to All scenarios, supports search and per-scenario refresh, and provides a multi-section lightbox plus baseline/current/diff review. A long page's numbered viewport images belong to one reference. Approval accepts the whole page, including added or removed sections; inspect all sections and approve only intentional changes. Capture never updates baselines automatically.

Both catalogs are included by default (`--suite all`). Use `--suite pages` or `--suite states` to narrow coverage. `--all` only forces recapture of the selected catalog. Direct runners use `VISUAL_PAGE` and `VISUAL_SUITE`.

## Keep capture independent of page contents

- Render production routes, views, safe areas, native sheets, and controls. Keep capture orchestration outside `mobile/app/`, `mobile/src/`, `web/src/`, `desktop/src/`, and checked-in native code.
- Mock infrastructure inputs and side effects in the family's harness, not screen copies. Do not add production capture flags, branches, imports, or bot-only accessibility identifiers.
- Navigate directly where possible. Use semantic selectors only for interactions necessary to reach a destination, not to assert which cards or text should exist before capturing.
- Readiness means fonts/boot handoff and stable pixels. An unstable image fails; a missing or changed component should produce a reviewable image instead of a selector timeout.
- Scroll coverage is automatic: geometry in the browser, repeated native swipes until pixels stop changing. Do not scroll to a named last card. Chat and live feeds may intentionally remain viewport references.
- Keep native timers running while wall time is fixed. Use the real OS keyboard when needed. Device frames are gallery CSS, never baked into captures.

## Extend coverage

First look for an existing page. Add a new page only for a new destination or meaningful presentation context.

Web: register `page`, `route`, and `scroll: "page"` in `web/visual/scenarios.json`; add fixture state and minimal navigation in `web/visual/drives/pages.ts`. Existing fixture data may be reused without inheriting feature-tour actions.

Mobile: register the page and its flow in `mobile/visual/scenarios.json`. Follow `mobile/maestro/pages/settings.yml`: clean state, deterministic permissions, real deep link, `wait-for-launch.yml`, report screenshot, then `capture-page.yml`. A viewport-only reference uses `capture-screenshot.js`. Both helpers write the stable images to the shared store. Native form sheets need clean presentation history.

Fixtures live in each family's `visual/harness/`; mobile registers substitutions in `visual/metro.config.js`. Match production contracts and preserve unrelated user edits. Shared mechanics live in `visual/{store,stability,fingerprint,comparison,selection}.mjs` and `visual/gallery/`.

## Verify and diagnose

Run the affected `check.sh` slices from the repository root: `app-visual`, `app-web`, and/or `app-mobile`. Capture the affected pages on touched runners and inspect their pixels, not just a passing runner result. Generated `.visual/` artifacts remain ignored.

Use the gallery's status and reports, or `visual/.visual/capture-<runner>.log`. An eight-second stability timeout reports a capture failure rather than saving an unsettled frame. The page viewport cap also fails incomplete captures.

Avoid `--skip-build` after app or harness edits. It reuses installed binaries without rebundling, and every iOS shard must have the same current bundle. Ordinary source edits use the normal runner's fast rebundle path. Use `--clean-native` for stale native caches, especially after moving the checkout.

Web owns loopback port 1431 and refuses reuse of another dev server. The gallery defaults to 4173; choose `--port` if occupied. Never stop an unrelated development process to reclaim a port.
