import { describe, expect, it } from "vitest";

import { parseArguments } from "./visual-android.mjs";

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
