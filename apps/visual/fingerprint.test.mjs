import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";

import path from "node:path";
import { describe, expect, it } from "vitest";
import { fingerprintInputs, staleReasons } from "./fingerprint.mjs";
import { appsRoot } from "./platforms.mjs";

describe("fingerprintInputs", () => {
  it("hashes the same files and extras to the same fingerprint, in any order", async () => {
    const a = await fingerprintInputs(
      ["visual/platforms.mjs", "visual/store.mjs"],
      ["card"],
    );
    const b = await fingerprintInputs(
      ["visual/store.mjs", "visual/platforms.mjs"],
      ["card"],
    );
    expect(a.fingerprint).toBe(b.fingerprint);
    expect(a.sources).toEqual(["visual/platforms.mjs", "visual/store.mjs"]);
    expect(Object.keys(a.hashes)).toEqual(a.sources);
  });
  it("changes with an extra and with a missing file", async () => {
    const base = await fingerprintInputs(["visual/platforms.mjs"], ["card"]);
    const other = await fingerprintInputs(
      ["visual/platforms.mjs"],
      ["card v2"],
    );
    const missing = await fingerprintInputs(
      ["visual/platforms.mjs", "visual/nope.mjs"],
      ["card"],
    );
    expect(other.fingerprint).not.toBe(base.fingerprint);
    expect(missing.fingerprint).not.toBe(base.fingerprint);
    expect(missing.hashes["visual/nope.mjs"]).toBe("missing");
  });
});

describe("staleReasons", () => {
  it("names the files whose content moved and the set changes", async () => {
    // The store directory is gitignored, so a fresh checkout has none until a capture runs.
    const store = path.join(appsRoot, "visual/.visual");
    await mkdir(store, { recursive: true });
    const directory = await mkdtemp(path.join(store, "fp-test-"));
    const relative = path.relative(appsRoot, directory);
    await writeFile(path.join(directory, "a.ts"), "one");
    await writeFile(path.join(directory, "b.ts"), "two");
    const before = await fingerprintInputs(
      [`${relative}/a.ts`, `${relative}/b.ts`],
      ["card"],
    );
    await writeFile(path.join(directory, "a.ts"), "changed");
    const after = await fingerprintInputs(
      [`${relative}/a.ts`, `${relative}/c.ts`],
      ["card v2"],
    );
    await rm(directory, { recursive: true, force: true });
    expect(staleReasons(before, after)).toEqual({
      changed: [`${relative}/a.ts`],
      added: [`${relative}/c.ts`],
      removed: [`${relative}/b.ts`],
      extras: true,
      unknown: false,
    });
  });
  it("reports a record without hashes as unknown", async () => {
    const after = await fingerprintInputs(["visual/platforms.mjs"], []);
    expect(staleReasons({ fingerprint: "x", sources: [] }, after).unknown).toBe(
      true,
    );
  });
});
