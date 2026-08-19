import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  captureBothThemes,
  flowFailureError,
  gentleSpawnPlan,
  grabUntilStable,
  maestroFlowSummary,
  startScreenshotBridge,
} from "./visual-runner.mjs";

describe("maestroFlowSummary", () => {
  it("folds sharded and unsharded result lines into pass/fail lists", () => {
    const output = [
      "[shard 2] [Passed] Connected app screens (1m 16s)",
      '[shard 1] [Failed] Recent gateways and reconnection (33s) (Assertion is false: "Try again" is visible)',
      "[Passed] Gateway update screens (27m 7s)",
      "[Failed] Connected home empty state (1m 39s)",
      "Waiting for flows to complete...",
    ].join("\n");
    expect(maestroFlowSummary(output)).toEqual({
      passed: ["Connected app screens", "Gateway update screens"],
      failed: [
        {
          name: "Recent gateways and reconnection",
          reason: 'Assertion is false: "Try again" is visible',
        },
        { name: "Connected home empty state", reason: "" },
      ],
    });
  });

  it("names the failing flows on the enriched error", () => {
    const error = new Error("maestro exited with 1.");
    error.stdout =
      '[shard 1] [Passed] Connect (49s)\n[shard 1] [Failed] Recent gateways (33s) (Assertion is false: "Try again" is visible)\n';
    error.stderr = "";
    expect(flowFailureError(error).message).toBe(
      '1 of 2 flows failed: Recent gateways (Assertion is false: "Try again" is visible)',
    );
  });

  it("keeps the original error when no flow results are present", () => {
    const error = new Error("maestro exited with 1.");
    expect(flowFailureError(error)).toBe(error);
  });
});

describe("gentleSpawnPlan", () => {
  it.each([
    ["off", false, "darwin", "xcodebuild", ["build"]],
    ["non-darwin", true, "linux", "gradle", ["assembleRelease"]],
  ])(
    "passes commands through when %s",
    (_name, gentle, platform, command, args) => {
      expect(gentleSpawnPlan(command, args, gentle, platform)).toEqual({
        command,
        argumentsList: args,
      });
    },
  );

  it("wraps the command at utility QoS when gentle on macOS", () => {
    expect(
      gentleSpawnPlan("maestro", ["test", "flow.yml"], true, "darwin"),
    ).toEqual({
      command: "taskpolicy",
      argumentsList: ["-c", "utility", "maestro", "test", "flow.yml"],
    });
  });
});

// Vitest resolves a missing named export to undefined, so only a real Node
// import proves the runner modules link: this is what a scan spawns.
describe("runner modules", () => {
  it.each(["visual-runner.mjs", "visual-ios.mjs", "visual-android.mjs"])(
    "%s links under Node ESM",
    async (file) => {
      const target = fileURLToPath(new URL(`./${file}`, import.meta.url));
      const result = spawnSync(
        process.execPath,
        [
          "--input-type=module",
          "-e",
          `await import(${JSON.stringify(target)});`,
        ],
        { encoding: "utf8" },
      );
      expect(result.stderr).toBe("");
      expect(result.status).toBe(0);
    },
  );
});

describe("grabUntilStable", () => {
  it("returns the first grab that repeats, polling until then", async () => {
    const frames = ["a", "b", "b", "c"].map((text) => Buffer.from(text));
    let calls = 0;
    const grab = () =>
      Promise.resolve(frames[Math.min(calls++, frames.length - 1)]);
    const stable = await grabUntilStable(grab, { pollMs: 1 });
    expect(stable.toString()).toBe("b");
    expect(calls).toBe(3);
  });

  it("gives up with the last grab when the picture never settles", async () => {
    let calls = 0;
    const grab = () => Promise.resolve(Buffer.from(String(calls++)));
    const last = await grabUntilStable(grab, { pollMs: 1, timeoutMs: 20 });
    expect(Number(last.toString())).toBeGreaterThan(1);
    expect(Number(last.toString())).toBe(calls - 1);
  });
});

describe("captureBothThemes", () => {
  it("stores the light shot, flips dark, stores the sibling, and flips back", async () => {
    const events = [];
    let dark = false;
    const grab = () => Promise.resolve(Buffer.from(dark ? "dark" : "light"));
    await captureBothThemes({
      platform: "ios",
      name: "home.png",
      grab,
      setDark: (value) => {
        dark = value;
        events.push(`dark=${value}`);
        return Promise.resolve();
      },
      store: (platform, name, image) => {
        events.push(`${platform}:${name}:${image.toString()}`);
        return Promise.resolve();
      },
    });
    expect(events).toEqual([
      "ios:home.png:light",
      "dark=true",
      "ios-dark:home.png:dark",
      "dark=false",
    ]);
    expect(dark).toBe(false);
  });
});

describe("startScreenshotBridge", () => {
  it("answers a failed capture with its message and keeps serving the cycle", async () => {
    let attempts = 0;
    const bridge = await startScreenshotBridge(["sim"], {
      capture: () => {
        attempts += 1;
        return attempts === 1
          ? Promise.reject(new Error("screencap failed"))
          : Promise.resolve();
      },
    });
    try {
      const cycle = await bridge.beginCycle({
        scenarios: [{ screenshot: "home.png" }, { screenshot: "chat.png" }],
      });
      const post = (screenshot) =>
        fetch(bridge.urls[0], {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ screenshot }),
        });
      const failed = await post("home.png");
      expect(failed.status).toBe(500);
      expect(await failed.text()).toBe("screencap failed");
      const served = await post("chat.png");
      expect(served.status).toBe(204);
      cycle.settle();
      await expect(cycle.completion).resolves.toBeUndefined();
      expect([...cycle.seen]).toEqual(["chat.png"]);
    } finally {
      await bridge.close();
    }
  });
});
