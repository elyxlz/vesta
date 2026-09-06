import { loadAllRegistries } from "./registry.mjs";
import { PLATFORMS, themedSibling } from "./platforms.mjs";
import { captureSelection, selectRegistry } from "./selection.mjs";
import { readShotRecord, shotEntries, storeDirectory } from "./store.mjs";

export async function selectedScenarios(selection = captureSelection()) {
  return Object.values(await loadAllRegistries()).flatMap((registry) =>
    selectRegistry(registry, { ...selection, page: "" }).scenarios.filter(
      (scenario) =>
        !selection.page ||
        scenario.page === selection.page ||
        scenario.id === selection.page,
    ),
  );
}

// Index only the selected suite. Both themes share one record read, and the
// live gallery receives the same viewport manifest as the initial HTML.
export async function catalogShots(scenarios, directory = storeDirectory) {
  const shots = await shotEntries(
    directory,
    new Set(scenarios.map((scenario) => scenario.screenshot)),
  );
  const records = new Map();
  await Promise.all(
    Object.entries(shots).flatMap(([platform, entries]) =>
      scenarios.map(async (scenario) => {
        const entry = entries[scenario.screenshot];
        if (!entry) return;
        const light =
          PLATFORMS[platform].theme === "light"
            ? platform
            : themedSibling(platform, "light");
        const key = `${light}/${scenario.screenshot}`;
        if (!records.has(key))
          records.set(
            key,
            readShotRecord(light, scenario.screenshot, directory),
          );
        const record = await records.get(key);
        entry.parts = record?.parts ?? [scenario.screenshot];
        entry.complete =
          Boolean(record) &&
          entry.parts.every((name) => Boolean(entries[name]));
      }),
    ),
  );
  return shots;
}
