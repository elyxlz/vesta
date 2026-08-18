import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { FAMILIES, PLATFORMS, platformsOfFamily } from "./platforms.mjs";

const SCENARIO_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function requireText(scenario, field) {
  if (typeof scenario[field] !== "string" || !scenario[field].trim()) {
    throw new Error(`Visual scenario ${scenario.id ?? "?"} needs a ${field}.`);
  }
}

function validateScenario(entry, family, familyPlatforms, ids, screenshots) {
  if (!SCENARIO_ID.test(entry.id ?? "")) {
    throw new Error(`Invalid visual scenario id: ${entry.id}`);
  }
  if (ids.has(entry.id)) {
    throw new Error(`Duplicate visual scenario id: ${entry.id}`);
  }
  requireText(entry, "title");
  requireText(entry, "description");
  requireText(entry, "group");
  const screenshot = entry.screenshot ?? `${entry.id}.png`;
  if (
    path.basename(screenshot) !== screenshot ||
    path.extname(screenshot) !== ".png"
  ) {
    throw new Error(`Invalid screenshot name for ${entry.id}.`);
  }
  if (screenshots.has(screenshot)) {
    throw new Error(`Duplicate screenshot name: ${screenshot}`);
  }
  if (
    "platforms" in entry &&
    (!Array.isArray(entry.platforms) ||
      entry.platforms.length === 0 ||
      entry.platforms.some((name) => !familyPlatforms.includes(name)))
  ) {
    throw new Error(`Invalid platforms for ${entry.id}.`);
  }
  ids.add(entry.id);
  screenshots.add(screenshot);
  return { ...entry, family, screenshot };
}

function validateFlows(manifest, flowRoot) {
  if (!Array.isArray(manifest.flows) || manifest.flows.length === 0) {
    throw new Error("The mobile visual registry must define at least one flow.");
  }
  if (typeof manifest.appId !== "string" || !manifest.appId) {
    throw new Error("The mobile visual registry must define appId.");
  }
  for (const flow of manifest.flows) {
    const flowPath = path.resolve(flowRoot, flow);
    if (!flowPath.startsWith(`${flowRoot}${path.sep}`)) {
      throw new Error(`Flow escapes the mobile workspace: ${flow}`);
    }
    if (!existsSync(flowPath)) {
      throw new Error(`Visual flow does not exist: ${flow}`);
    }
  }
}

// One contract for every family: card data the gallery reads, plus whatever state
// the family's runner needs, passed through untouched.
export function validateRegistry(manifest, family, options = {}) {
  if (!FAMILIES[family]) throw new Error(`Unknown family: ${family}`);
  if (manifest.version !== 1) {
    throw new Error(`Unsupported visual registry version: ${manifest.version}`);
  }
  if (!Array.isArray(manifest.scenarios) || manifest.scenarios.length === 0) {
    throw new Error("The visual registry must define at least one scenario.");
  }
  const familyPlatforms = platformsOfFamily(family);
  const ids = new Set();
  const screenshots = new Set();
  const scenarios = manifest.scenarios.map((entry) =>
    validateScenario(entry, family, familyPlatforms, ids, screenshots),
  );
  if (family === "mobile") {
    validateFlows(
      manifest,
      options.flowRoot ?? path.dirname(path.dirname(FAMILIES.mobile.registry)),
    );
  }
  return { ...manifest, family, scenarios };
}

export async function loadRegistry(family) {
  if (!FAMILIES[family]) throw new Error(`Unknown family: ${family}`);
  const manifest = JSON.parse(await readFile(FAMILIES[family].registry, "utf8"));
  return validateRegistry(manifest, family);
}

// Ids and screenshot names are unique within a family; across families the
// same screen keeps the same id (shots live in per-platform directories, and
// the gallery keys nothing on a family-wide id).
export async function loadAllRegistries() {
  const registries = {};
  for (const family of Object.keys(FAMILIES)) {
    registries[family] = await loadRegistry(family);
  }
  return registries;
}

export function scenarioOnPlatform(scenario, platform) {
  return (
    !Array.isArray(scenario.platforms) || scenario.platforms.includes(platform)
  );
}

export function scenariosForPlatform(registry, platform) {
  return registry.scenarios.filter((scenario) =>
    scenarioOnPlatform(scenario, platform),
  );
}

export function excludedNote(scenario) {
  const labels = (scenario.platforms ?? []).map(
    (platform) => PLATFORMS[platform]?.label ?? platform,
  );
  return `${labels.join(" + ")} only`;
}
