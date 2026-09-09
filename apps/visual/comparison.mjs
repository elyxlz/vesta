import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile } from "node:fs/promises";
import { constants } from "node:fs";
import path from "node:path";
import { PNG } from "pngjs";
import pixelmatch from "pixelmatch";
import {
  atomicWriteFile,
  readShotRecord,
  shotPath,
  storeDirectory,
} from "./store.mjs";
import { loadAllRegistries, scenarioOnPlatform } from "./registry.mjs";
import { PLATFORMS, themedSibling } from "./platforms.mjs";
import { captureSelection, selectRegistry } from "./selection.mjs";

const digest = (buffer) => createHash("sha256").update(buffer).digest("hex");
const comparisonVersion = 1;

async function readOptional(file) {
  try {
    return await readFile(file);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

function pathsFor(platform, name, directory) {
  const current = shotPath(platform, name, directory);
  return {
    current,
    baseline: path.join(directory, "baselines", platform, name),
    record: path.join(directory, "comparisons", platform, `${name}.json`),
  };
}

export function comparePixels(baseline, current) {
  const before = PNG.sync.read(baseline);
  const after = PNG.sync.read(current);
  const dimensions = {
    baselineSize: { width: before.width, height: before.height },
    currentSize: { width: after.width, height: after.height },
  };
  if (before.width !== after.width || before.height !== after.height) {
    return {
      ...dimensions,
      status: "resized",
      pixels: null,
      ratio: null,
      diff: null,
    };
  }
  const diff = new PNG({ width: after.width, height: after.height });
  // Ignore antialiasing noise, but report any remaining changed pixel. There
  // is no whole-screen allowance that could hide a missing small control.
  const pixels = pixelmatch(
    before.data,
    after.data,
    diff.data,
    after.width,
    after.height,
    {
      threshold: 0.1,
      includeAA: false,
    },
  );
  return {
    ...dimensions,
    status: pixels === 0 ? "same" : "changed",
    pixels,
    ratio: pixels / (after.width * after.height),
    diff: pixels ? PNG.sync.write(diff) : null,
  };
}

// Review images are addressed by content, so a capture arriving while a user
// reviews a change cannot swap the pixels under the approval button.
async function reviewImage(buffer, directory) {
  const src = `review-images/${digest(buffer)}.png`;
  await atomicWriteFile(path.join(directory, src), buffer);
  return src;
}

export async function compareShot(
  platform,
  name,
  directory = storeDirectory,
  removed = false,
  added = false,
) {
  const paths = pathsFor(platform, name, directory);
  const [current, baseline] = await Promise.all([
    removed ? null : readOptional(paths.current),
    added ? null : readOptional(paths.baseline),
  ]);
  if (!current)
    return {
      platform,
      name,
      status: removed ? "removed" : "missing",
      currentHash: null,
      baseline: baseline ? await reviewImage(baseline, directory) : null,
    };
  const currentHash = digest(current);
  const baselineHash = baseline ? digest(baseline) : null;
  const saved = await readOptional(paths.record);
  if (saved) {
    let cached;
    try {
      cached = JSON.parse(saved.toString());
    } catch {
      // A disposable cache must not prevent review of intact captures.
    }
    if (
      cached?.version === comparisonVersion &&
      cached.currentHash === currentHash &&
      cached.baselineHash === baselineHash
    )
      return cached;
  }
  const result = {
    version: comparisonVersion,
    platform,
    name,
    currentHash,
    baselineHash,
    current: await reviewImage(current, directory),
    baseline: baseline ? await reviewImage(baseline, directory) : null,
    status: "new",
  };
  if (baseline) {
    const { diff, ...comparison } = comparePixels(baseline, current);
    Object.assign(result, comparison, {
      diff: diff ? await reviewImage(diff, directory) : null,
    });
  } else {
    // A corrupt new PNG is a capture failure, not an approvable baseline.
    PNG.sync.read(current);
  }
  await atomicWriteFile(paths.record, `${JSON.stringify(result)}\n`);
  return result;
}

export async function approveShot(
  platform,
  name,
  expectedHash,
  directory = storeDirectory,
) {
  const paths = pathsFor(platform, name, directory);
  const current = await readFile(paths.current);
  if (digest(current) !== expectedHash)
    throw new Error(
      "The capture changed during review. Review it again before approving.",
    );
  PNG.sync.read(current);
  await atomicWriteFile(paths.baseline, current);
}

export async function comparisonTargets(
  platform,
  selection = captureSelection(),
) {
  if (platform && !Object.hasOwn(PLATFORMS, platform))
    throw new Error(`Unknown platform: ${platform}`);
  const scenarios = Object.values(await loadAllRegistries()).flatMap(
    (registry) =>
      selectRegistry(registry, { ...selection, page: "" }).scenarios.filter(
        (scenario) =>
          !selection.page ||
          scenario.page === selection.page ||
          scenario.id === selection.page,
      ),
  );
  return Object.entries(PLATFORMS).flatMap(([id, definition]) =>
    platform && platform !== id
      ? []
      : scenarios
          .filter(
            (scenario) =>
              scenario.family === definition.family &&
              scenarioOnPlatform(scenario, id),
          )
          .map((scenario) => ({ platform: id, name: scenario.screenshot })),
  );
}

async function currentParts(platform, name, directory) {
  return (await currentRecord(platform, name, directory))?.parts ?? [name];
}

async function currentRecord(platform, name, directory) {
  const light =
    PLATFORMS[platform].theme === "light"
      ? platform
      : themedSibling(platform, "light");
  return readShotRecord(light, name, directory);
}

function partsPath(platform, name, directory) {
  return `${pathsFor(platform, name, directory).baseline}.parts.json`;
}

async function baselineParts(platform, name, directory) {
  const data = await readOptional(partsPath(platform, name, directory));
  if (!data) return [name];
  const parts = JSON.parse(data.toString());
  if (!Array.isArray(parts) || parts[0] !== name)
    throw new Error("Invalid baseline page manifest");
  for (const part of parts) shotPath(platform, part, directory);
  return parts;
}

export async function comparePage(platform, name, directory = storeDirectory) {
  shotPath(platform, name, directory);
  const current = await currentParts(platform, name, directory);
  const baseline = await baselineParts(platform, name, directory);
  const parts = [];
  for (const part of new Set([...current, ...baseline]))
    parts.push(
      await compareShot(
        platform,
        part,
        directory,
        !current.includes(part),
        !baseline.includes(part),
      ),
    );
  const currentHash = digest(
    Buffer.from(
      JSON.stringify(parts.map((part) => [part.name, part.currentHash])),
    ),
  );
  const status = !(await currentRecord(platform, name, directory))
    ? "incomplete"
    : parts.every((part) => part.status === "same")
      ? "same"
      : parts.some((part) => part.status === "missing")
        ? "missing"
        : parts.every((part) => part.status === "new")
          ? "new"
          : "changed";
  return { platform, name, status, currentHash, parts };
}

export async function approvePage(
  platform,
  name,
  expectedHash,
  directory = storeDirectory,
) {
  const reviewed = await comparePage(platform, name, directory);
  if (
    reviewed.currentHash !== expectedHash ||
    ["missing", "incomplete"].includes(reviewed.status)
  )
    throw new Error(
      "The page changed during review or is incomplete. Review it again before approving.",
    );
  const parts = reviewed.parts.filter((part) => part.status !== "removed");
  const images = [];
  for (const part of parts) {
    const bytes = await readFile(
      pathsFor(platform, part.name, directory).current,
    );
    if (digest(bytes) !== part.currentHash)
      throw new Error(
        "The page changed during review. Review it again before approving.",
      );
    images.push({ name: part.name, bytes });
  }
  for (const image of images)
    await atomicWriteFile(
      pathsFor(platform, image.name, directory).baseline,
      image.bytes,
    );
  await atomicWriteFile(
    partsPath(platform, name, directory),
    JSON.stringify(parts.map((part) => part.name)),
  );
}

// Explicit initialization only: existing baselines are never overwritten.
export async function seedBaselines(targets, directory = storeDirectory) {
  let seeded = 0;
  for (const { platform, name } of targets) {
    if (await readOptional(partsPath(platform, name, directory))) continue;
    if (!(await currentRecord(platform, name, directory))) continue;
    const parts = await currentParts(platform, name, directory);
    for (const part of parts) {
      const paths = pathsFor(platform, part, directory);
      await mkdir(path.dirname(paths.baseline), { recursive: true });
      try {
        await copyFile(paths.current, paths.baseline, constants.COPYFILE_EXCL);
        seeded += 1;
      } catch (error) {
        if (error.code !== "ENOENT" && error.code !== "EEXIST") throw error;
      }
    }
    const manifest = partsPath(platform, name, directory);
    // Seeding is only for a page with no baseline manifest; never accept a
    // newly added viewport on an already-reviewed page as a side effect.
    if (
      !(await readOptional(manifest)) &&
      (await readOptional(pathsFor(platform, name, directory).baseline))
    )
      await atomicWriteFile(manifest, JSON.stringify(parts));
  }
  return seeded;
}
