import { PLATFORMS, themedSibling } from "./platforms.mjs";
import { scenarioOnPlatform } from "./registry.mjs";
import { captureSelection } from "./selection.mjs";
import { readShotRecord, shotPath } from "./store.mjs";
import { catalogShots, selectedScenarios } from "./catalog.mjs";

// Machine-readable counterparts of the gallery cards. Absolute local paths
// can go straight to an agent's image viewer; no browser inspection is needed.
export async function referenceIndex(
  selection = captureSelection(),
  platform = "",
) {
  if (platform && !Object.hasOwn(PLATFORMS, platform))
    throw new Error(`Unknown platform: ${platform}`);
  const scenarios = await selectedScenarios(selection);
  const shots = await catalogShots(scenarios);
  const references = [];
  for (const scenario of scenarios) {
    if (
      selection.page &&
      scenario.page !== selection.page &&
      scenario.id !== selection.page
    )
      continue;
    for (const [id, definition] of Object.entries(PLATFORMS)) {
      if (
        (platform && id !== platform) ||
        scenario.family !== definition.family ||
        !scenarioOnPlatform(scenario, id)
      )
        continue;
      const shot = shots[id]?.[scenario.screenshot];
      const light =
        definition.theme === "light" ? id : themedSibling(id, "light");
      const record = await readShotRecord(light, scenario.screenshot);
      references.push({
        page: scenario.page ?? null,
        id: scenario.id,
        title: scenario.title,
        route: scenario.route ?? null,
        platform: id,
        capturedAt: shot ? new Date(shot.mtime).toISOString() : null,
        imagePath: shot ? shotPath(id, scenario.screenshot) : null,
        imageUrl: shot?.src ?? null,
        galleryPath: `/?suite=${selection.suite}#${scenario.family}-${scenario.id}`,
        captureStatus: !shot
          ? "missing"
          : shot.complete
            ? "captured"
            : "incomplete",
        freshness: "unchecked; refresh skips unchanged inputs",
        fingerprint: record?.fingerprint ?? null,
        inputCount: record?.sources.length ?? 0,
        images: (record?.parts ?? [scenario.screenshot]).map((name) => ({
          name,
          path: shots[id]?.[name] ? shotPath(id, name) : null,
          url: shots[id]?.[name]?.src ?? null,
        })),
        refresh: `npm run visual:capture -- ${definition.runner} --suite ${selection.suite} --page ${scenario.page ?? scenario.id}`,
      });
    }
  }
  if (selection.page && !references.length)
    throw new Error(`No page matches ${selection.page}`);
  return { suite: selection.suite, references };
}
