import {
  captureAllRequested,
  fingerprintInputs,
  staleReasons,
} from "@vesta/visual/fingerprint";
import { PLATFORMS, themedSibling } from "@vesta/visual/platforms";
import { loadRegistry, scenarioOnPlatform } from "@vesta/visual/registry";
import { readShotRecord, shotIsFresh } from "@vesta/visual/store";
import { scenarioInputs } from "./freshness-inputs.mjs";

// The web plan: which scenarios a capture would retake on which projects, as
// one line of JSON, the same decision capture.spec.ts makes per test.
const registry = await loadRegistry("web");
const captureAll = captureAllRequested();
const projects = Object.entries(PLATFORMS)
  .filter(
    ([, platform]) => platform.family === "web" && platform.theme === "light",
  )
  .map(([name]) => name);

const units = [];
for (const scenario of registry.scenarios) {
  const inputs = await scenarioInputs(scenario.id, scenario);
  const stalePlatforms = [];
  let reasons = null;
  for (const project of projects) {
    if (!scenarioOnPlatform(scenario, project)) continue;
    const dark = themedSibling(project, "dark");
    const platforms =
      dark && scenarioOnPlatform(scenario, dark) ? [project, dark] : [project];
    const record = await readShotRecord(project, scenario.screenshot);
    const current =
      record === null
        ? null
        : await fingerprintInputs(
            [...record.sources, ...inputs.files],
            inputs.extras,
          );
    const fresh =
      !captureAll &&
      current !== null &&
      (await shotIsFresh(platforms, scenario.screenshot, current.fingerprint));
    if (fresh) continue;
    stalePlatforms.push(project);
    // The first stale project names the reason; the others share the inputs.
    reasons ??=
      record === null || current === null
        ? {
            changed: [],
            added: [],
            removed: [],
            extras: false,
            unknown: false,
            missing: [scenario.screenshot],
          }
        : { ...staleReasons(record, current), missing: [] };
  }
  units.push({
    name: scenario.id,
    shots: [scenario.screenshot],
    stale: stalePlatforms.length > 0,
    platforms: stalePlatforms,
    reasons,
  });
}
process.stdout.write(`${JSON.stringify({ runner: "web", units })}\n`);
