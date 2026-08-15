import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { Page } from "@playwright/test";
import { test } from "./test-options";
import { SCENARIOS } from "./scenarios";
import { installSyncSocket } from "./harness/sync-fixtures";
import { installGatewayMocks } from "./harness/http-fixtures";
import { seedStorage } from "./harness/storage";

const OUT_DIR = path.resolve(import.meta.dirname, "../.visual/web");
const STABLE_POLL_MS = 150;
const STABLE_MAX_TRIES = 20;

test.beforeAll(() => {
  mkdirSync(OUT_DIR, { recursive: true });
});

// A settle assertion can pass while a Motion enter-fade is still running
// (Playwright counts opacity 0 as visible), so capture only once two
// consecutive frames match. The orb never settles by design; after the try
// budget the last frame is accepted as the orb's known nondeterminism.
async function stableScreenshot(page: Page, file: string): Promise<void> {
  const shoot = () =>
    page.screenshot({ animations: "disabled", caret: "hide" });
  let previous = await shoot();
  for (let attempt = 0; attempt < STABLE_MAX_TRIES; attempt += 1) {
    await page.waitForTimeout(STABLE_POLL_MS);
    const next = await shoot();
    if (next.equals(previous)) break;
    previous = next;
  }
  writeFileSync(file, previous);
}

for (const scenario of SCENARIOS) {
  test(scenario.id, async ({ page, theme }, testInfo) => {
    await seedStorage(page, theme);
    await installSyncSocket(page, scenario.deltas);
    await installGatewayMocks(page, {
      agentStatus: scenario.agentStatus,
      createResponse: scenario.createResponse,
    });
    await page.goto("/new");
    await scenario.drive(page);
    await scenario.settle(page);
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await stableScreenshot(
      page,
      path.join(OUT_DIR, `${scenario.id}--${testInfo.project.name}.png`),
    );
  });
}
