import { mkdir, mkdtemp, readdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  atomicWriteFile,
  platformShotsDirectory,
  pngSize,
  putShot,
  shotDriftWarning,
  shotEntries,
  shotsDirectory,
} from "./store.mjs";

// A minimal PNG header: signature, IHDR length, "IHDR", width, height.
function pngHeader(width, height) {
  const buffer = Buffer.alloc(24);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(buffer, 0);
  buffer.writeUInt32BE(13, 8);
  buffer.write("IHDR", 12, "ascii");
  buffer.writeUInt32BE(width, 16);
  buffer.writeUInt32BE(height, 20);
  return buffer;
}

describe("paths", () => {
  it("keys the store by platform id under apps/visual/.visual/shots", () => {
    expect(platformShotsDirectory("web-dark")).toBe(
      path.join(shotsDirectory, "web-dark"),
    );
    expect(
      shotsDirectory.endsWith(path.join("apps", "visual", ".visual", "shots")),
    ).toBe(true);
  });
});

describe("putShot", () => {
  it("copies a shot into the platform directory and leaves no temp file behind", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-store-"));
    const source = path.join(base, "source.png");
    await writeFile(source, pngHeader(1, 2));
    await putShot("ios", "home.png", source, base);
    const target = path.join(base, "shots", "ios");
    expect(await readdir(target)).toEqual(["home.png"]);
    expect(
      (await readFile(path.join(target, "home.png"))).equals(pngHeader(1, 2)),
    ).toBe(true);
  });

  it("writes a Buffer through the same temp-and-rename path", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-store-"));
    await putShot("ios-dark", "home.png", pngHeader(3, 4), base);
    const target = path.join(base, "shots", "ios-dark");
    expect(await readdir(target)).toEqual(["home.png"]);
    expect(
      (await readFile(path.join(target, "home.png"))).equals(pngHeader(3, 4)),
    ).toBe(true);
  });

  it("rejects a name that is not a bare .png filename", async () => {
    await expect(putShot("ios", "../home.png", "/dev/null")).rejects.toThrow(
      /Invalid shot name/,
    );
    await expect(putShot("ios", "home.jpg", "/dev/null")).rejects.toThrow(
      /Invalid shot name/,
    );
  });

  it("rejects an unknown platform", async () => {
    await expect(putShot("tv", "home.png", "/dev/null")).rejects.toThrow(
      /Unknown platform: tv/,
    );
  });
});

describe("shotEntries", () => {
  it("indexes shot files per platform with store-relative sources", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-store-"));
    await mkdir(path.join(base, "shots", "ios"), { recursive: true });
    await mkdir(path.join(base, "shots", "web-dark"), { recursive: true });
    await writeFile(path.join(base, "shots", "ios", "home.png"), pngHeader(1, 2));
    await writeFile(path.join(base, "shots", "ios", "notes.txt"), "ignored");
    await writeFile(
      path.join(base, "shots", "web-dark", "done.png"),
      pngHeader(3, 4),
    );
    const entries = await shotEntries(base);
    expect(Object.keys(entries.ios)).toEqual(["home.png"]);
    expect(entries.ios["home.png"].src).toBe("shots/ios/home.png");
    expect(typeof entries.ios["home.png"].mtime).toBe("number");
    expect(entries["web-dark"]["done.png"].src).toBe("shots/web-dark/done.png");
    expect(entries.android).toEqual({});
  });

  it("serves every platform empty while the store does not exist", async () => {
    const entries = await shotEntries(
      path.join(os.tmpdir(), "visual-store-missing"),
    );
    expect(Object.keys(entries).sort()).toEqual([
      "android",
      "android-dark",
      "android-galaxy",
      "android-galaxy-dark",
      "desktop",
      "desktop-dark",
      "ios",
      "ios-dark",
      "web",
      "web-dark",
      "web-narrow",
      "web-narrow-dark",
    ]);
    expect(
      Object.values(entries).every((entry) => Object.keys(entry).length === 0),
    ).toBe(true);
  });
});

describe("pngSize", () => {
  it("reads the IHDR dimensions and rejects a non-PNG", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-store-"));
    await writeFile(path.join(base, "a.png"), pngHeader(640, 480));
    await writeFile(path.join(base, "b.png"), "not a png at all, just text");
    expect(await pngSize(path.join(base, "a.png"))).toEqual({
      width: 640,
      height: 480,
    });
    expect(await pngSize(path.join(base, "b.png"))).toBeNull();
  });
});

describe("shotDriftWarning", () => {
  const scenarios = [{ screenshot: "a.png" }, { screenshot: "b.png" }];
  it("is empty when the produced shots match the registry", () => {
    expect(shotDriftWarning(new Set(["a.png", "b.png"]), scenarios)).toBe("");
  });
  it("names missing and unexpected shots without refusing the run", () => {
    expect(shotDriftWarning(new Set(["a.png", "z.png"]), scenarios)).toBe(
      "missing: b.png; unexpected: z.png",
    );
  });
});

describe("atomicWriteFile", () => {
  it("writes through a temp file and leaves only the target", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-store-"));
    const target = path.join(base, "nested", "status.json");
    await atomicWriteFile(target, "{}\n");
    expect(await readFile(target, "utf8")).toBe("{}\n");
    expect(await readdir(path.dirname(target))).toEqual(["status.json"]);
  });
});
