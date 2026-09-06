import { expect, test, type Page } from "@playwright/test";
import { captureAllRequested } from "@vesta/visual/fingerprint";
import { PLATFORMS, themedSibling } from "@vesta/visual/platforms";
import { loadRegistry, scenarioOnPlatform } from "@vesta/visual/registry";
import { grabUntilStable } from "@vesta/visual/stability";
import { selectRegistry } from "@vesta/visual/selection";
import {
  putShot,
  putShotRecord,
  readShotRecord,
  shotIsFresh,
} from "@vesta/visual/store";
import { SCENARIOS } from "./drives";
import { installChatSocket } from "./harness/chat-fixtures";
import {
  coverageSources,
  scenarioInputs,
  shotFingerprint,
} from "./harness/freshness";
import { installGatewayMocks } from "./harness/http-fixtures";
import { installNativeStub } from "./harness/native-stub";
import { installReadiness, waitForReadiness } from "./harness/readiness";
import { preparePageScroll, scrollPage } from "./harness/page-scroll";
import { FIXED_TIME, type ScenarioState } from "./harness/scenario-state";
import { seedStorage } from "./harness/storage";
import { installSyncSocket } from "./harness/sync-fixtures";

const registry = selectRegistry(await loadRegistry("web"));
const captureAll = captureAllRequested();

// Run before the page fixture: unchanged shots need neither a browser page
// nor a context. BrowserName is a worker option, not a launched browser.
test.beforeEach(async ({ browserName }, testInfo) => {
  test.skip(browserName !== "chromium", "Source coverage requires Chromium");
  const scenario = registry.scenarios.find(
    (entry) => entry.id === testInfo.title,
  );
  if (!scenario)
    throw new Error(`No scenario registered for ${testInfo.title}`);
  test.skip(!scenarioOnPlatform(scenario, testInfo.project.name));
  if (captureAll) return;
  const record = await readShotRecord(
    testInfo.project.name,
    scenario.screenshot,
  );
  if (!record) return;
  const inputs = await scenarioInputs(scenario.id, scenario);
  const current = await shotFingerprint(record.sources, inputs);
  const dark = themedSibling(testInfo.project.name, "dark");
  const platforms =
    dark && scenarioOnPlatform(scenario, dark)
      ? [testInfo.project.name, dark]
      : [testInfo.project.name];
  test.skip(
    await shotIsFresh(platforms, scenario.screenshot, current.fingerprint),
    "unchanged since the last capture",
  );
});

// The store is the only copy: putShot takes the screenshot buffer straight from
// the page, and the registry's screenshot name is the file the gallery reads.
async function shoot(
  page: Page,
  platform: string,
  screenshot: string,
): Promise<void> {
  await waitForReadiness(page);
  const shot = await grabUntilStable(async () => {
    await waitForReadiness(page);
    return page.screenshot({ animations: "disabled", caret: "hide" });
  });
  await putShot(platform, screenshot, shot);
}

async function shootPage(
  page: Page,
  platform: string,
  name: string,
  scroll: boolean,
) {
  await shoot(page, platform, name);
  const scrollable = scroll && (await preparePageScroll(page));
  const positions = [0];
  const parts = [name];
  if (scrollable) {
    await shoot(page, platform, name);
    for (;;) {
      const next = await scrollPage(page);
      if (next === positions.at(-1)) break;
      if (parts.length >= 24)
        throw new Error("Page exceeded 24 viewports; capture is incomplete");
      positions.push(next);
      const part = name.replace(
        /\.png$/,
        `--${String(parts.length + 1).padStart(2, "0")}.png`,
      );
      parts.push(part);
      await shoot(page, platform, part);
    }
  }
  return { scrollable, positions, parts };
}

async function installState(
  page: Page,
  state: ScenarioState,
  desktop: boolean,
): Promise<void> {
  if (desktop) {
    await installNativeStub(page, {
      platform: state.native?.platform,
      connection: state.connection,
      appUpdate: state.native?.appUpdate,
    });
  }
  await seedStorage(page, {
    connection: state.connection,
    extra: state.storage,
  });
  await page.clock.setFixedTime(FIXED_TIME);
  await installReadiness(page);
  await installSyncSocket(page, state.sync);
  await installGatewayMocks(page, state.routes ?? []);
  if (state.chatSocket) {
    await installChatSocket(
      page,
      state.chatSocket.agent,
      state.chatSocket.events,
    );
  }
}

// Reduced motion and stable pixels gate capture, not assertions on the UI.
for (const scenario of registry.scenarios) {
  test(scenario.id, async ({ page }, testInfo) => {
    test.skip(
      !scenarioOnPlatform(scenario, testInfo.project.name),
      "scenario is scoped to other platforms",
    );
    const platform = Object.entries(PLATFORMS).find(
      ([id]) => id === testInfo.project.name,
    )?.[1];
    if (!platform)
      throw new Error(`No platform registered for ${testInfo.project.name}`);
    const definition = SCENARIOS[scenario.id];
    if (!definition) throw new Error(`No drive registered for ${scenario.id}`);
    const dark = themedSibling(testInfo.project.name, "dark");
    const darkWanted = dark !== null && scenarioOnPlatform(scenario, dark);
    const inputs = await scenarioInputs(scenario.id, scenario);
    const state = definition.state ?? {};
    await installState(page, state, platform.frame === "desktop-window");
    await page.coverage.startJSCoverage({ resetOnNavigation: false });
    await page.goto(state.route ?? "/new");
    await waitForReadiness(page);
    await definition.drive(page);
    // Park the pointer so no card renders its hover state in the shot.
    await page.mouse.move(0, 0);
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    const { scrollable, positions, parts } = await shootPage(
      page,
      testInfo.project.name,
      scenario.screenshot,
      scenario.page !== undefined && scenario.scroll === "page",
    );
    // The theme is "system", so flipping the emulated scheme is what the OS
    // would do: the app re-themes in place and the dark shot needs no re-drive.
    if (darkWanted) {
      await page.emulateMedia({ colorScheme: "dark" });
      await expect(page.locator("html")).toHaveClass(/\bdark\b/);
      for (const [index, name] of parts.entries()) {
        if (scrollable) await scrollPage(page, positions[index]);
        await shoot(page, dark, name);
      }
    }
    const coverage = await page.coverage.stopJSCoverage();
    const executed = coverageSources(coverage);
    await putShotRecord(testInfo.project.name, scenario.screenshot, {
      ...(await shotFingerprint(executed, inputs)),
      parts,
    });
  });
}
