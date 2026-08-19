import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { appsRoot } from "./platforms.mjs";

// One fingerprint over a set of source files plus any extra strings a scan
// contributes (a scenario's card, a flow's text): sha256 over each file's
// apps-relative path and content hash in sorted order, so the same inputs hash
// the same on every machine and a missing file is a distinct input. The
// per-file hashes ride along in the record, so a later plan can name the files
// that changed instead of only reporting a mismatch.
export async function fingerprintInputs(sourceFiles, extras = []) {
  const hash = createHash("sha256");
  const relative = [
    ...new Set(sourceFiles.map((file) => toAppsRelative(file))),
  ].sort();
  const hashes = {};
  for (const file of relative) {
    hashes[file] = await hashFile(path.join(appsRoot, file));
    hash.update(`${file}\n${hashes[file]}\n`);
  }
  const extrasHash = createHash("sha256");
  for (const extra of extras) extrasHash.update(`${extra}\n`);
  const extrasDigest = extrasHash.digest("hex");
  hash.update(`extras\n${extrasDigest}\n`);
  return {
    fingerprint: hash.digest("hex"),
    sources: relative,
    hashes,
    extras: extrasDigest,
  };
}

async function hashFile(file) {
  try {
    return createHash("sha256")
      .update(await readFile(file))
      .digest("hex");
  } catch {
    return "missing";
  }
}

// Why a recorded shot is stale against a fresh fingerprint: the files whose
// hash moved, files that entered or left the set, and whether the inputs
// outside files (the card, the flow's own extras) changed.
export function staleReasons(record, current) {
  if (!record.hashes) {
    return {
      changed: [],
      added: [],
      removed: [],
      extras: false,
      unknown: true,
    };
  }
  const before = record.hashes;
  const after = current.hashes ?? {};
  const changed = Object.keys(after).filter(
    (file) => file in before && before[file] !== after[file],
  );
  const added = Object.keys(after).filter((file) => !(file in before));
  const removed = Object.keys(before).filter((file) => !(file in after));
  const extras = Boolean(record.extras) && record.extras !== current.extras;
  return { changed, added, removed, extras, unknown: false };
}

export function toAppsRelative(file) {
  return path.isAbsolute(file) ? path.relative(appsRoot, file) : file;
}

// Process-wide: `--all` on a runner or `?all=1` on the gallery's capture POST
// sets VISUAL_CAPTURE_ALL, and every shot is taken again.
export function captureAllRequested(argv = process.argv) {
  return process.env.VISUAL_CAPTURE_ALL === "1" || argv.includes("--all");
}
