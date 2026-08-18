import { mkdir, readdir, readFile, utimes, writeFile } from "node:fs/promises";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { parseArguments, stageMaestroShots } from "./visual-android.mjs";

describe("parseArguments", () => {
  it("captures on the dedicated AVD by default", () => {
    const options = parseArguments([]);
    expect(options.command).toBe("capture");
    expect(options.avd).toBe("vesta-visual");
    expect(options.variant).toBe("android");
  });

  it("accepts a specific adb device, a visible emulator, and a variant", () => {
    const options = parseArguments([
      "capture",
      "--device",
      "emulator-5554",
      "--show-emulator",
      "--variant",
      "android-galaxy",
    ]);
    expect(options.device).toBe("emulator-5554");
    expect(options.showEmulator).toBe(true);
    expect(options.variant).toBe("android-galaxy");
    expect(options.avd).toBe("vesta-visual-galaxy");
  });

  it("parses gentle mode off by default and on by flag", () => {
    expect(parseArguments([]).gentle).toBe(false);
    expect(parseArguments(["capture", "--gentle"]).gentle).toBe(true);
  });

  it("rejects contradictory build options", () => {
    expect(() => parseArguments(["--skip-build", "--clean-native"])).toThrow(
      "--skip-build and --clean-native cannot be used together.",
    );
  });

  it("rejects a command other than capture", () => {
    expect(() => parseArguments(["serve"])).toThrow("Unknown command: serve");
  });
});

describe("stageMaestroShots", () => {
  it("stages takeScreenshot artifacts into the shots directory by name", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-stage-"));
    const source = path.join(base, "maestro");
    const target = path.join(base, "shots/android");
    await mkdir(path.join(source, "flow-a/takeScreenshot"), { recursive: true });
    await mkdir(target, { recursive: true });
    await writeFile(
      path.join(source, "flow-a/takeScreenshot/connect.png"),
      "new-shot",
    );
    await writeFile(path.join(source, "flow-a/stray.png"), "not-an-artifact");
    await writeFile(path.join(target, "connect.png"), "old-shot");
    await writeFile(path.join(target, "untouched.png"), "kept");

    const staged = await stageMaestroShots(source, "android", base);

    expect(staged.produced).toEqual(new Set(["connect.png"]));
    expect(staged.duplicates).toEqual([]);
    expect(await readFile(path.join(target, "connect.png"), "utf8")).toBe(
      "new-shot",
    );
    expect(await readFile(path.join(target, "untouched.png"), "utf8")).toBe(
      "kept",
    );
    expect((await readdir(target)).sort()).toEqual([
      "connect.png",
      "untouched.png",
    ]);
  });

  it("keeps the newest artifact for a name duplicated across flows", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-stage-"));
    const source = path.join(base, "maestro");
    const target = path.join(base, "shots/android");
    const older = path.join(source, "flow-a/takeScreenshot/connect.png");
    const newer = path.join(source, "flow-b/takeScreenshot/connect.png");
    await mkdir(path.dirname(older), { recursive: true });
    await mkdir(path.dirname(newer), { recursive: true });
    await writeFile(older, "older-shot");
    await writeFile(newer, "newer-shot");
    await utimes(older, new Date(1000), new Date(1000));
    await utimes(newer, new Date(2000), new Date(2000));

    const staged = await stageMaestroShots(source, "android", base);

    expect(staged.produced).toEqual(new Set(["connect.png"]));
    expect(staged.duplicates).toEqual(["connect.png"]);
    expect(await readFile(path.join(target, "connect.png"), "utf8")).toBe(
      "newer-shot",
    );
  });
});
