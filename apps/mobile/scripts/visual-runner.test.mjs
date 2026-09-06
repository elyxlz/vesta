import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import {
  captureBothThemes,
  createPageCapture,
  isNativeSource,
  isJsBundleInput,
  flowFailureError,
  gentleSpawnPlan,
  grabUntilStable,
  maestroFlowSummary,
  startScreenshotBridge,
  selectMobileRegistry,
  scenariosInSelectedFlow,
} from "./visual-runner.mjs";

describe("focused mobile captures", () => {
  const registry = {
    family: "mobile",
    flows: ["chat.yml", "settings.yml"],
    scenarios: [
      { id: "delivery", screenshot: "delivery.png" },
      { id: "conversation", screenshot: "conversation.png" },
      { id: "ios-only", screenshot: "ios-only.png", platforms: ["ios"] },
      { id: "settings", screenshot: "settings.png", page: "settings" },
    ],
  };
  const shots = ["delivery.png", "conversation.png", "ios-only.png"];

  it("plans all captures in a selected flow, excluding unsupported platforms", () => {
    const manifest = selectMobileRegistry(registry, "android", {
      suite: "states",
      page: "conversation",
    });
    expect(manifest.scenarios.map((s) => s.id)).toEqual(["conversation"]);
    expect(scenariosInSelectedFlow(manifest, shots).map((s) => s.id)).toEqual([
      "delivery",
      "conversation",
    ]);
    expect(scenariosInSelectedFlow(manifest, ["settings.png"])).toEqual([]);
  });

  it("retains iOS-only siblings and never mutates the original registry", () => {
    const manifest = selectMobileRegistry(registry, "ios", {
      suite: "all",
      page: "conversation",
    });
    expect(scenariosInSelectedFlow(manifest, shots)).toEqual(
      registry.scenarios.slice(0, 3),
    );
    expect(registry.scenarios).toHaveLength(4);
  });

  it("keeps page-suite selection out of unrelated state flows", () => {
    const manifest = selectMobileRegistry(registry, "ios", {
      suite: "pages",
      page: "",
    });
    expect(scenariosInSelectedFlow(manifest, shots)).toEqual([]);
    expect(scenariosInSelectedFlow(manifest, ["settings.png"])).toEqual([
      registry.scenarios[3],
    ]);
  });
});

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
    const stable = await grabUntilStable(grab, { pollMs: 1, stableMs: 0 });
    expect(stable.toString()).toBe("b");
    expect(calls).toBe(3);
  });

  it("fails when the picture never settles instead of saving an unstable frame", async () => {
    vi.useFakeTimers();
    try {
      let calls = 0;
      const grab = () => Promise.resolve(Buffer.from(String(calls++)));
      const result = expect(
        grabUntilStable(grab, { pollMs: 1, timeoutMs: 20 }),
      ).rejects.toThrow("Screenshot did not settle within 20 ms.");
      await vi.runAllTimersAsync();
      await result;
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("captureBothThemes", () => {
  it.each(["switch", "grab", "store"])(
    "restores light appearance after a dark %s failure",
    async (failure) => {
      let dark = false;
      const changes = [];
      const stored = [];
      await expect(
        captureBothThemes({
          platform: "ios",
          name: "home.png",
          grab: async () => {
            if (dark && failure === "grab") throw new Error("dark grab failed");
            return Buffer.from(dark ? "dark" : "light");
          },
          setDark: async (value) => {
            dark = value;
            changes.push(value);
            if (value && failure === "switch")
              throw new Error("dark switch failed");
          },
          store: async (platform) => {
            if (platform === "ios-dark" && failure === "store")
              throw new Error("dark store failed");
            stored.push(platform);
          },
        }),
      ).rejects.toThrow(`dark ${failure} failed`);
      expect(changes).toEqual([true, false]);
      expect(dark).toBe(false);
      expect(stored).toEqual(["ios"]);
    },
  );

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

describe("page capture", () => {
  it("captures each new viewport in both themes and stops at identical pixels", async () => {
    vi.useFakeTimers();
    try {
      const capture = createPageCapture();
      const stored = [];
      let frame = "top";
      let dark = false;
      const options = {
        platform: "ios",
        name: "page.png",
        grab: async () => Buffer.from(`${frame}:${dark}`),
        setDark: async (value) => {
          dark = value;
        },
        store: async (platform, name) => {
          stored.push(`${platform}/${name}`);
        },
      };
      const first = capture(options, "start");
      await vi.runAllTimersAsync();
      expect(await first).toEqual({ more: true });
      frame = "bottom";
      const next = capture(options, "next");
      await vi.runAllTimersAsync();
      expect(await next).toEqual({ more: true });
      const last = capture(options, "next");
      await vi.runAllTimersAsync();
      expect(await last).toEqual({ more: false });
      expect(stored).toEqual([
        "ios/page.png",
        "ios-dark/page.png",
        "ios/page--02.png",
        "ios-dark/page--02.png",
      ]);
      expect(dark).toBe(false);
      await expect(capture(options, "next")).rejects.toThrow("has not started");
    } finally {
      vi.useRealTimers();
    }
  });

  it("fails an unbounded page instead of marking a truncated capture complete", async () => {
    vi.useFakeTimers();
    try {
      const capture = createPageCapture();
      let frame = 0;
      const options = {
        platform: "ios",
        name: "page.png",
        grab: async () => Buffer.from(String(frame)),
        setDark: async () => {},
        store: async () => {},
      };
      const first = capture(options, "start");
      await vi.runAllTimersAsync();
      await first;
      for (frame = 1; frame < 24; frame += 1) {
        const next = capture(options, "next");
        await vi.runAllTimersAsync();
        await next;
      }
      const exceeded = expect(capture(options, "next")).rejects.toThrow(
        "exceeded 24 viewports",
      );
      await vi.runAllTimersAsync();
      await exceeded;
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("isNativeSource", () => {
  it("does not rebundle for documentation but retains fixture inputs", () => {
    expect(isJsBundleInput("/apps/mobile/visual/README.md")).toBe(false);
    expect(isJsBundleInput("/apps/mobile/visual/.agents/agent.yaml")).toBe(
      false,
    );
    expect(isJsBundleInput("/apps/mobile/visual/harness/clock.js")).toBe(true);
    expect(isJsBundleInput("/apps/mobile/visual/harness/data.json")).toBe(true);
  });
  it("keeps sources and drops build outputs", () => {
    expect(
      isNativeSource("/apps/mobile/modules/vesta-share/src/index.ts"),
    ).toBe(true);
    expect(
      isNativeSource("/apps/mobile/modules/vesta-share/android/build/x.bin"),
    ).toBe(false);
    expect(
      isNativeSource("/apps/mobile/modules/vesta-share/android/.gradle/y"),
    ).toBe(false);
    expect(
      isNativeSource("/apps/mobile/modules/vesta-share/ios/DerivedData/z"),
    ).toBe(false);
  });
});

describe("startScreenshotBridge", () => {
  it("does not finish a page cycle while additional viewports are pending", async () => {
    const bridge = await startScreenshotBridge(["sim"], {
      capture: async (_target, _name, step) => ({ more: step === "start" }),
    });
    try {
      const cycle = await bridge.beginCycle({
        scenarios: [{ screenshot: "page.png" }],
      });
      const post = (screenshot, pageStep) =>
        fetch(bridge.urls[0], {
          method: "POST",
          body: JSON.stringify({ screenshot, pageStep }),
        });
      expect((await post("unexpected.png", "start")).status).toBe(500);
      expect(await (await post("page.png", "start")).json()).toEqual({
        more: true,
      });
      expect([...cycle.seen]).toEqual([]);
      expect(await (await post("page.png", "next")).json()).toEqual({
        more: false,
      });
      await cycle.completion;
      expect([...cycle.seen]).toEqual(["page.png"]);
    } finally {
      await bridge.close();
    }
  });
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
      expect(served.status).toBe(200);
      cycle.settle();
      await expect(cycle.completion).resolves.toBeUndefined();
      expect([...cycle.seen]).toEqual(["chat.png"]);
    } finally {
      await bridge.close();
    }
  });
});
