import { describe, expect, it } from "vitest";

import { catalogScenarios, parseArguments } from "./visual-catalog-android.mjs";

describe("parseArguments", () => {
  it("captures on the dedicated AVD by default", () => {
    const options = parseArguments([]);
    expect(options.command).toBe("capture");
    expect(options.avd).toBe("vesta-visual");
    expect(options.serve).toBe(true);
    expect(options.port).toBe(4174);
  });

  it("accepts a specific adb device and a headless override", () => {
    const options = parseArguments([
      "capture",
      "--device",
      "emulator-5554",
      "--show-emulator",
      "--no-serve",
    ]);
    expect(options.device).toBe("emulator-5554");
    expect(options.showEmulator).toBe(true);
    expect(options.serve).toBe(false);
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

  it("rejects an unknown command", () => {
    expect(() => parseArguments(["watch"])).toThrow("Unknown command: watch");
  });
});

describe("catalogScenarios", () => {
  it("keeps manifest order and marks iOS-only scenarios instead of dropping them", () => {
    const scenarios = catalogScenarios(
      [
        { id: "captured-state", screenshot: "captured-state.png" },
        {
          id: "ios-only-state",
          screenshot: "ios-only-state.png",
          platforms: ["ios"],
        },
      ],
      "release-1",
      new Map([["captured-state.png", { width: 1080, height: 2400 }]]),
    );

    expect(scenarios.map((scenario) => scenario.id)).toEqual([
      "captured-state",
      "ios-only-state",
    ]);
    expect(scenarios[0]).toMatchObject({
      captured: true,
      image: "screenshots/release-1/captured-state.png",
      size: { width: 1080, height: 2400 },
    });
    expect(scenarios[1]).toMatchObject({
      captured: false,
      image: "",
      missingLabel: "iOS only",
    });
  });
});
