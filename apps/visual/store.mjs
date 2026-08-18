import {
  copyFile,
  mkdir,
  readdir,
  readFile,
  rename,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { PLATFORMS, visualRoot } from "./platforms.mjs";

// The one shot store: one PNG per scenario per platform, replaced in place as a
// scan captures it, so a failed or partial run leaves the entries it did not reach untouched.
export const storeDirectory = path.join(visualRoot, ".visual");
export const shotsDirectory = path.join(storeDirectory, "shots");

export function platformShotsDirectory(platform, baseDirectory = storeDirectory) {
  if (!PLATFORMS[platform]) throw new Error(`Unknown platform: ${platform}`);
  return path.join(baseDirectory, "shots", platform);
}

let temporaryFileCounter = 0;

export async function atomicWriteFile(target, contents) {
  await mkdir(path.dirname(target), { recursive: true });
  temporaryFileCounter += 1;
  const temporary = `${target}.${process.pid}.${temporaryFileCounter}.tmp`;
  await writeFile(temporary, contents);
  await rename(temporary, target);
}

// The only writer of shot files: write (a Buffer) or copy (a path) to a temp name
// in the target directory, then rename, so the gallery's poll never reads a torn PNG.
export async function putShot(
  platform,
  name,
  source,
  baseDirectory = storeDirectory,
) {
  if (
    typeof name !== "string" ||
    path.basename(name) !== name ||
    !name.endsWith(".png")
  ) {
    throw new Error(`Invalid shot name: ${name}`);
  }
  const directory = platformShotsDirectory(platform, baseDirectory);
  await mkdir(directory, { recursive: true });
  const target = path.join(directory, name);
  const temporary = `${target}.tmp-${process.pid}`;
  if (Buffer.isBuffer(source)) await writeFile(temporary, source);
  else await copyFile(source, temporary);
  await rename(temporary, target);
}

// Index of the shot files on disk: platform -> filename -> {src, mtime}, with src
// relative to the store root so the page can load and cache-bust it.
export async function shotEntries(baseDirectory = storeDirectory) {
  const platforms = Object.keys(PLATFORMS);
  const entries = Object.fromEntries(
    platforms.map((platform) => [platform, {}]),
  );
  for (const platform of platforms) {
    const directory = path.join(baseDirectory, "shots", platform);
    const names = await readdir(directory).catch(() => []);
    for (const name of names) {
      if (!name.endsWith(".png")) continue;
      try {
        const mtime = Math.round(
          (await stat(path.join(directory, name))).mtimeMs,
        );
        entries[platform][name] = { src: `shots/${platform}/${name}`, mtime };
      } catch {
        continue;
      }
    }
  }
  return entries;
}

export async function pngSize(filePath) {
  const file = await readFile(filePath);
  if (
    file.length < 24 ||
    file.toString("ascii", 1, 4) !== "PNG" ||
    file.toString("ascii", 12, 16) !== "IHDR"
  ) {
    return null;
  }
  return { width: file.readUInt32BE(16), height: file.readUInt32BE(20) };
}

// A scan warns about registry drift instead of refusing: the shot files it
// replaced stay valid either way.
export function shotDriftWarning(producedNames, scenarios) {
  const expected = scenarios.map((scenario) => scenario.screenshot);
  const missing = expected.filter((name) => !producedNames.has(name));
  const unexpected = [...producedNames]
    .filter((name) => !expected.includes(name))
    .sort();
  const parts = [];
  if (missing.length > 0) parts.push(`missing: ${missing.join(", ")}`);
  if (unexpected.length > 0) parts.push(`unexpected: ${unexpected.join(", ")}`);
  return parts.join("; ");
}
