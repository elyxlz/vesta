import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { appsRoot } from "@vesta/visual/platforms";

// What a web shot depends on beyond the modules the page executed: the shell
// and global styles every screen renders through, the harness that shapes the
// world, the capture mechanics, the dependency lockfile, and the drives file
// that defines the scenario. Shared by the capture (which records a shot's
// sources) and the plan (which re-checks them without a browser).
const visualDirectory = path.dirname(fileURLToPath(import.meta.url));
const harnessDirectory = path.join(visualDirectory, "harness");
const drivesDirectory = path.join(visualDirectory, "drives");

export async function alwaysOnInputs() {
  const harness = (await readdir(harnessDirectory))
    .filter((name) => name.endsWith(".ts") && !name.endsWith(".test.ts"))
    .map((name) => path.join(harnessDirectory, name));
  return [
    ...harness,
    path.join(visualDirectory, "freshness-inputs.mjs"),
    path.join(visualDirectory, "capture.spec.ts"),
    path.join(visualDirectory, "playwright.config.ts"),
    path.join(appsRoot, "web/index.html"),
    path.join(appsRoot, "web/vite.config.ts"),
    path.join(appsRoot, "web/src/index.css"),
    path.join(appsRoot, "web/src/design-tokens.css"),
    path.join(appsRoot, "package-lock.json"),
  ];
}

// The drives file that defines a scenario: the one whose text carries the id
// as a key of its scenario record.
export async function drivesFileFor(id) {
  const key = new RegExp(`^\\s*(?:"${id}"|${id}):`, "m");
  for (const name of (await readdir(drivesDirectory)).sort()) {
    if (!name.endsWith(".ts") || name === "index.ts") continue;
    const file = path.join(drivesDirectory, name);
    if (key.test(await readFile(file, "utf8"))) return file;
  }
  throw new Error(`No drives file defines the scenario ${id}.`);
}

export async function scenarioInputs(id, card) {
  return {
    files: [...(await alwaysOnInputs()), await drivesFileFor(id)],
    extras: [JSON.stringify(card)],
  };
}
