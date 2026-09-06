import {
  copyFile,
  mkdir,
  open,
  readFile,
  readdir,
  rename,
  stat,
  unlink,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { PLATFORMS, visualRoot } from "./platforms.mjs";

// The one shot store: one PNG per scenario per platform, replaced in place as a
// scan captures it, so a failed or partial run leaves the entries it did not reach untouched.
export const storeDirectory = path.join(visualRoot, ".visual");
export const shotsDirectory = path.join(storeDirectory, "shots");

export function platformShotsDirectory(
  platform,
  baseDirectory = storeDirectory,
) {
  if (!Object.hasOwn(PLATFORMS, platform))
    throw new Error(`Unknown platform: ${platform}`);
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
  const target = shotPath(platform, name, baseDirectory);
  const directory = path.dirname(target);
  await mkdir(directory, { recursive: true });
  temporaryFileCounter += 1;
  const temporary = `${target}.tmp-${process.pid}-${temporaryFileCounter}`;
  if (Buffer.isBuffer(source)) await writeFile(temporary, source);
  else await copyFile(source, temporary);
  // Replacing light invalidates the pair until both themes finish. A failed
  // forced recapture must not reuse the previous run's freshness record.
  await unlink(shotRecordPath(platform, name, baseDirectory)).catch((error) => {
    if (error.code !== "ENOENT") throw error;
  });
  await rename(temporary, target);
}

export function shotPath(platform, name, baseDirectory = storeDirectory) {
  if (
    typeof name !== "string" ||
    path.basename(name) !== name ||
    !name.endsWith(".png")
  ) {
    throw new Error(`Invalid shot name: ${name}`);
  }
  return path.join(platformShotsDirectory(platform, baseDirectory), name);
}

// Index of the shot files on disk: platform -> filename -> {src, mtime}, with src
// relative to the store root so the page can load and cache-bust it.
export async function shotEntries(baseDirectory = storeDirectory, names) {
  const platforms = Object.keys(PLATFORMS);
  const entries = Object.fromEntries(
    platforms.map((platform) => [platform, {}]),
  );
  await Promise.all(
    platforms.map(async (platform) => {
      const directory = path.join(baseDirectory, "shots", platform);
      const files = (await readdir(directory).catch(() => [])).filter(
        (name) =>
          name.endsWith(".png") &&
          (!names ||
            names.has(name) ||
            names.has(name.replace(/--\d+\.png$/, ".png"))),
      );
      await Promise.all(
        files.map(async (name) => {
          // A shot replaced between readdir and stat is simply absent this tick.
          const info = await stat(path.join(directory, name)).catch(() => null);
          if (!info) return;
          entries[platform][name] = {
            src: `shots/${platform}/${name}`,
            mtime: Math.round(info.mtimeMs),
          };
        }),
      );
    }),
  );
  return entries;
}

// Reads only the 24-byte header (signature + IHDR), never the whole image.
const PNG_HEADER_BYTES = 24;

export async function pngSize(filePath) {
  const file = await open(filePath, "r");
  const header = Buffer.alloc(PNG_HEADER_BYTES);
  let bytesRead;
  try {
    ({ bytesRead } = await file.read(header, 0, PNG_HEADER_BYTES, 0));
  } finally {
    await file.close();
  }
  if (
    bytesRead < PNG_HEADER_BYTES ||
    header.toString("ascii", 1, 4) !== "PNG" ||
    header.toString("ascii", 12, 16) !== "IHDR"
  ) {
    return null;
  }
  return { width: header.readUInt32BE(16), height: header.readUInt32BE(20) };
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

// Beside every light shot sits its freshness record: the fingerprint of the
// inputs that produced it and the source files the fingerprint covers. A
// scan recaptures a shot only when that fingerprint no longer matches.
export function shotRecordPath(platform, name, baseDirectory = storeDirectory) {
  return shotPath(platform, name, baseDirectory).replace(/\.png$/, ".fp");
}

export async function putShotRecord(
  platform,
  name,
  record,
  baseDirectory = storeDirectory,
) {
  await atomicWriteFile(
    shotRecordPath(platform, name, baseDirectory),
    `${JSON.stringify(record)}\n`,
  );
}

export async function readShotRecord(
  platform,
  name,
  baseDirectory = storeDirectory,
) {
  try {
    const text = await readFile(
      shotRecordPath(platform, name, baseDirectory),
      "utf8",
    );
    const record = JSON.parse(text);
    return record !== null &&
      typeof record.fingerprint === "string" &&
      Array.isArray(record.sources) &&
      record.sources.every((source) => typeof source === "string") &&
      (record.parts === undefined ||
        (Array.isArray(record.parts) &&
          record.parts.length > 0 &&
          record.parts[0] === name &&
          record.parts.every(
            (part) =>
              typeof part === "string" &&
              path.basename(part) === part &&
              part.endsWith(".png"),
          )))
      ? record
      : null;
  } catch {
    return null;
  }
}

// Fresh means the light shot's record carries this fingerprint and every
// listed platform holds the shot file: a missing dark sibling recaptures both.
export async function shotIsFresh(
  platforms,
  name,
  fingerprint,
  baseDirectory = storeDirectory,
) {
  const [light] = platforms;
  const record = await readShotRecord(light, name, baseDirectory);
  if (!record || record.fingerprint !== fingerprint) return false;
  for (const platform of platforms) {
    try {
      for (const part of record.parts ?? [name])
        await stat(shotPath(platform, part, baseDirectory));
    } catch {
      return false;
    }
  }
  return true;
}
