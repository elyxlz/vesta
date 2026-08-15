import { mkdirSync } from "node:fs";
import path from "node:path";
import { test } from "./test-options";
import { SCENARIOS } from "./scenarios";
import { installSyncSocket } from "./harness/sync-fixtures";
import { installGatewayMocks } from "./harness/http-fixtures";
import { seedStorage } from "./harness/storage";

const OUT_DIR = path.resolve(import.meta.dirname, "../.visual/web");

test.beforeAll(() => {
  mkdirSync(OUT_DIR, { recursive: true });
});

// The context runs with reducedMotion: "reduce", which the app treats as "no
// animation at all" (instant swaps, snapped orb), so a single screenshot after
// the settle assertion is already the final frame.
for (const scenario of SCENARIOS) {
  test(scenario.id, async ({ page, theme }, testInfo) => {
    await seedStorage(page, theme);
    await installSyncSocket(page, scenario.deltas);
    await installGatewayMocks(page, {
      agentStatus: scenario.agentStatus,
      createResponse: scenario.createResponse,
      hang: scenario.hang,
    });
    await page.goto("/new");
    await scenario.drive(page);
    await scenario.settle(page);
    // Park the pointer so no card renders its hover state in the shot.
    await page.mouse.move(0, 0);
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await page.screenshot({
      path: path.join(OUT_DIR, `${scenario.id}--${testInfo.project.name}.png`),
      animations: "disabled",
      caret: "hide",
    });
  });
}
