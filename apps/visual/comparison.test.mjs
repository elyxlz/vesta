import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { PNG } from "pngjs";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  approveShot,
  approvePage,
  comparePage,
  comparePixels,
  compareShot,
  comparisonTargets,
  seedBaselines,
} from "./comparison.mjs";
import { atomicWriteFile, putShot, putShotRecord } from "./store.mjs";

function png(width = 8, height = 8, color = 255) {
  const image = new PNG({ width, height });
  image.data.fill(color);
  for (let index = 3; index < image.data.length; index += 4)
    image.data[index] = 255;
  return PNG.sync.write(image);
}

describe("pixel comparisons", () => {
  it("reports identical pixels regardless of PNG encoding", () => {
    const original = png();
    const differentlyEncoded = PNG.sync.write(PNG.sync.read(original), {
      deflateLevel: 0,
    });
    expect(comparePixels(original, differentlyEncoded)).toMatchObject({
      status: "same",
      pixels: 0,
      diff: null,
    });
  });

  it("detects a removed control and produces a readable diff", () => {
    const before = PNG.sync.read(png());
    for (let y = 2; y < 6; y += 1) {
      for (let x = 2; x < 6; x += 1)
        before.data.fill(0, (y * 8 + x) * 4, (y * 8 + x) * 4 + 3);
    }
    const result = comparePixels(PNG.sync.write(before), png());
    expect(result).toMatchObject({
      status: "changed",
      pixels: 16,
      ratio: 0.25,
    });
    expect(PNG.sync.read(result.diff)).toMatchObject({ width: 8, height: 8 });
  });

  it("reports a dimension change instead of resizing away the regression", () => {
    expect(comparePixels(png(), png(9, 8))).toMatchObject({
      status: "resized",
      baselineSize: { width: 8, height: 8 },
      currentSize: { width: 9, height: 8 },
    });
  });
});

describe("baseline lifecycle", () => {
  let directory;
  beforeEach(async () => {
    directory = await mkdtemp(path.join(os.tmpdir(), "visual-compare-"));
  });
  afterEach(async () => {
    await rm(directory, { recursive: true, force: true });
  });

  it("marks missing and new captures without approving them", async () => {
    expect(await compareShot("web", "home.png", directory)).toMatchObject({
      status: "missing",
    });
    await putShot("web", "home.png", png(), directory);
    expect(await compareShot("web", "home.png", directory)).toMatchObject({
      status: "new",
      baseline: null,
    });
    await expect(
      readFile(path.join(directory, "baselines/web/home.png")),
    ).rejects.toMatchObject({ code: "ENOENT" });
  });

  it("keeps reviewed images immutable and refuses to approve a newer unseen capture", async () => {
    await putShot("web", "home.png", png(), directory);
    const review = await compareShot("web", "home.png", directory);
    await putShot("web", "home.png", png(8, 8, 0), directory);
    expect(await readFile(path.join(directory, review.current))).toEqual(png());
    await expect(
      approveShot("web", "home.png", review.currentHash, directory),
    ).rejects.toThrow("changed during review");
  });

  it("compares later captures against the approved image until explicitly approved", async () => {
    await putShot("web", "home.png", png(), directory);
    const first = await compareShot("web", "home.png", directory);
    await approveShot("web", "home.png", first.currentHash, directory);
    expect(await compareShot("web", "home.png", directory)).toMatchObject({
      status: "same",
    });
    await putShot("web", "home.png", png(8, 8, 0), directory);
    const changed = await compareShot("web", "home.png", directory);
    expect(changed).toMatchObject({ status: "changed", pixels: 64 });
    expect(
      await readFile(path.join(directory, "baselines/web/home.png")),
    ).toEqual(png());
    expect(await compareShot("web", "home.png", directory)).toEqual(changed);
    await approveShot("web", "home.png", changed.currentHash, directory);
    expect(await compareShot("web", "home.png", directory)).toMatchObject({
      status: "same",
    });
  });

  it("seeds existing captures once and preserves established baselines", async () => {
    const targets = [
      { platform: "web", name: "home.png" },
      { platform: "web", name: "absent.png" },
    ];
    await putShot("web", "home.png", png(), directory);
    await putShotRecord(
      "web",
      "home.png",
      { fingerprint: "v1", sources: [] },
      directory,
    );
    expect(await seedBaselines(targets, directory)).toBe(1);
    await putShot("web", "home.png", png(8, 8, 0), directory);
    expect(await seedBaselines(targets, directory)).toBe(0);
    expect(await compareShot("web", "home.png", directory)).toMatchObject({
      status: "changed",
    });
  });

  it("rebuilds a corrupt comparison cache from the images", async () => {
    await putShot("web", "home.png", png(), directory);
    const first = await compareShot("web", "home.png", directory);
    await atomicWriteFile(
      path.join(directory, "comparisons/web/home.png.json"),
      "{",
    );
    expect(await compareShot("web", "home.png", directory)).toEqual(first);
  });

  it("rejects corrupt PNGs and traversal targets", async () => {
    await putShot("web", "home.png", Buffer.from("broken"), directory);
    await expect(compareShot("web", "home.png", directory)).rejects.toThrow();
    await expect(compareShot("web", "../home.png", directory)).rejects.toThrow(
      "Invalid shot name",
    );
    await expect(
      compareShot("constructor", "home.png", directory),
    ).rejects.toThrow("Unknown platform");
  });

  it("reviews added and removed viewports as changes to the whole page", async () => {
    await putShot("web", "page.png", png(), directory);
    await putShotRecord(
      "web",
      "page.png",
      { fingerprint: "v1", sources: [], parts: ["page.png"] },
      directory,
    );
    const first = await comparePage("web", "page.png", directory);
    await approvePage("web", "page.png", first.currentHash, directory);
    await putShot("web", "page--02.png", png(8, 8, 0), directory);
    await putShotRecord(
      "web",
      "page.png",
      { fingerprint: "v2", sources: [], parts: ["page.png", "page--02.png"] },
      directory,
    );
    const longer = await comparePage("web", "page.png", directory);
    expect(longer.status).toBe("changed");
    expect(longer.parts.map((part) => part.status)).toEqual(["same", "new"]);
    expect(
      await seedBaselines([{ platform: "web", name: "page.png" }], directory),
    ).toBe(0);
    await approvePage("web", "page.png", longer.currentHash, directory);
    expect((await comparePage("web", "page.png", directory)).status).toBe(
      "same",
    );
    await putShotRecord(
      "web",
      "page.png",
      { fingerprint: "v3", sources: [], parts: ["page.png"] },
      directory,
    );
    const shorter = await comparePage("web", "page.png", directory);
    expect(shorter.parts.map((part) => part.status)).toEqual([
      "same",
      "removed",
    ]);
    await expect(
      approvePage("web", "page.png", longer.currentHash, directory),
    ).rejects.toThrow("changed during review");
    await approvePage("web", "page.png", shorter.currentHash, directory);
    expect((await comparePage("web", "page.png", directory)).status).toBe(
      "same",
    );
  });

  it("requires review when a previously removed section returns", async () => {
    await putShot("web", "page.png", png(), directory);
    await putShot("web", "page--02.png", png(), directory);
    await putShotRecord(
      "web",
      "page.png",
      { fingerprint: "v1", sources: [], parts: ["page.png", "page--02.png"] },
      directory,
    );
    const initial = await comparePage("web", "page.png", directory);
    await approvePage("web", "page.png", initial.currentHash, directory);
    await putShotRecord(
      "web",
      "page.png",
      { fingerprint: "v2", sources: [], parts: ["page.png"] },
      directory,
    );
    const shorter = await comparePage("web", "page.png", directory);
    await approvePage("web", "page.png", shorter.currentHash, directory);
    await putShotRecord(
      "web",
      "page.png",
      { fingerprint: "v3", sources: [], parts: ["page.png", "page--02.png"] },
      directory,
    );
    const restored = await comparePage("web", "page.png", directory);
    expect(restored.parts.map((part) => part.status)).toEqual(["same", "new"]);
  });

  it("refuses approval of a partial page capture", async () => {
    await putShot("web", "page.png", png(), directory);
    const partial = await comparePage("web", "page.png", directory);
    expect(partial.status).toBe("incomplete");
    expect(
      await seedBaselines([{ platform: "web", name: "page.png" }], directory),
    ).toBe(0);
    await expect(
      approvePage("web", "page.png", partial.currentHash, directory),
    ).rejects.toThrow("incomplete");
  });

  it("enumerates registered scenarios only on their supported platforms", async () => {
    const targets = await comparisonTargets("web");
    expect(targets).toContainEqual({
      platform: "web",
      name: "page-new-agent.png",
    });
    expect(new Set(targets.map((target) => target.platform))).toEqual(
      new Set(["web"]),
    );
    await expect(comparisonTargets("constructor")).rejects.toThrow(
      "Unknown platform",
    );
  });
});
