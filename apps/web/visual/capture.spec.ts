import { expect, test, type Page, type TestInfo } from "@playwright/test";
import type { AgentStatus, BuildPhase } from "@vesta/core";
import { PLATFORMS, themedSibling } from "@vesta/visual/platforms";
import { loadRegistry } from "@vesta/visual/registry";
import { putShot } from "@vesta/visual/store";
import { DRIVES } from "./drives";
import {
  AGENT,
  installGatewayMocks,
  type HangEndpoint,
  type ProviderInfoFixture,
} from "./harness/http-fixtures";
import { installNativeStub } from "./harness/native-stub";
import { seedStorage } from "./harness/storage";
import {
  agentDelta,
  aliveAgentNode,
  installSyncSocket,
  startingAgent,
} from "./harness/sync-fixtures";

// The registry carries the card data plus the JSON-serialisable state; the
// closures live in drives.ts. Typed here, at the boundary.
interface WebScenario {
  id: string;
  route?: string;
  agentStatus?: AgentStatus;
  createResponse?: { status: number; body: { error: string } } | null;
  deltas?: BuildPhase[];
  hang?: HangEndpoint;
  agentName?: string;
  provider?: ProviderInfoFixture;
}

const registry = await loadRegistry("web");
const scenarios = registry.scenarios as unknown as WebScenario[];

async function shoot(
  page: Page,
  testInfo: TestInfo,
  platform: string,
  id: string,
): Promise<void> {
  const shot = testInfo.outputPath(`${id}--${platform}.png`);
  await page.screenshot({ path: shot, animations: "disabled", caret: "hide" });
  await putShot(platform, `${id}.png`, shot);
}

// The context runs with reducedMotion: "reduce", which the app treats as "no
// animation at all", so a single screenshot after the settle assertion is the
// final frame.
for (const scenario of scenarios) {
  test(scenario.id, async ({ page }, testInfo) => {
    const platform = PLATFORMS[testInfo.project.name as keyof typeof PLATFORMS];
    if (platform.frame === "desktop-window") await installNativeStub(page);
    await seedStorage(page);
    await installSyncSocket(
      page,
      (scenario.deltas ?? []).map((phase) =>
        agentDelta(AGENT, startingAgent(phase)),
      ),
      scenario.agentName ? { [scenario.agentName]: aliveAgentNode() } : {},
    );
    await installGatewayMocks(page, {
      agentStatus: scenario.agentStatus ?? "starting",
      createResponse: scenario.createResponse ?? null,
      hang: scenario.hang,
      provider: scenario.provider,
    });
    await page.goto(scenario.route ?? "/new");
    const drive = DRIVES[scenario.id];
    if (!drive) throw new Error(`No drive registered for ${scenario.id}`);
    await drive.drive(page);
    await drive.settle(page);
    // Park the pointer so no card renders its hover state in the shot.
    await page.mouse.move(0, 0);
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await shoot(page, testInfo, testInfo.project.name, scenario.id);
    // The theme is "system", so flipping the emulated scheme is what the OS
    // would do: the app re-themes in place and the dark shot needs no re-drive.
    const dark = themedSibling(testInfo.project.name, "dark");
    if (!dark) return;
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await shoot(page, testInfo, dark, scenario.id);
  });
}
