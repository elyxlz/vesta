import { expect, test, type Page } from "@playwright/test";
import { captureAllRequested } from "@vesta/visual/fingerprint";
import { PLATFORMS, themedSibling } from "@vesta/visual/platforms";
import { loadRegistry, scenarioOnPlatform } from "@vesta/visual/registry";
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
import { FIXED_TIME, type ScenarioState } from "./harness/scenario-state";
import { seedStorage } from "./harness/storage";
import { installSyncSocket } from "./harness/sync-fixtures";

const registry = await loadRegistry("web");
const captureAll = captureAllRequested();

// The store is the only copy: putShot takes the screenshot buffer straight from
// the page, and the registry's screenshot name is the file the gallery reads.
async function shoot(
  page: Page,
  platform: string,
  screenshot: string,
): Promise<void> {
  const shot = await page.screenshot({ animations: "disabled", caret: "hide" });
  await putShot(platform, screenshot, shot);
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

// The context runs with reducedMotion: "reduce", which the app treats as "no
// animation at all", so a single screenshot after the settle assertion is the
// final frame.
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
    const shotPlatforms = darkWanted
      ? [testInfo.project.name, dark]
      : [testInfo.project.name];
    // A shot whose executed sources and inputs hash as they did last time is
    // fresh and skipped; --all (VISUAL_CAPTURE_ALL=1) retakes everything.
    const inputs = await scenarioInputs(scenario.id, scenario);
    const record = captureAll
      ? null
      : await readShotRecord(testInfo.project.name, scenario.screenshot);
    if (record) {
      const previous = await shotFingerprint(record.sources, inputs);
      test.skip(
        await shotIsFresh(
          shotPlatforms,
          scenario.screenshot,
          previous.fingerprint,
        ),
        "unchanged since the last capture",
      );
    }
    const state = definition.state ?? {};
    await installState(page, state, platform.frame === "desktop-window");
    await page.coverage.startJSCoverage({ resetOnNavigation: false });
    await page.goto(state.route ?? "/new");
    await definition.drive(page);
    await definition.settle(page);
    // Park the pointer so no card renders its hover state in the shot.
    await page.mouse.move(0, 0);
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await shoot(page, testInfo.project.name, scenario.screenshot);
    // The theme is "system", so flipping the emulated scheme is what the OS
    // would do: the app re-themes in place and the dark shot needs no re-drive.
    if (darkWanted) {
      await page.emulateMedia({ colorScheme: "dark" });
      await expect(page.locator("html")).toHaveClass(/\bdark\b/);
      await shoot(page, dark, scenario.screenshot);
    }
    const coverage = await page.coverage.stopJSCoverage();
    const executed = coverageSources(coverage);
    await putShotRecord(
      testInfo.project.name,
      scenario.screenshot,
      await shotFingerprint(executed, inputs),
    );
  });
}
