import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import {
  assignFlowsToShards,
  continuousShardFlow,
  createInactivityWatchdog,
  createMaestroFailureParser,
  flowFailureError,
  galleryHtml,
  galleryView,
  gentleSpawnPlan,
  maestroFlowSummary,
  newerRunStatus,
  loadManifest,
  scenarioOnPlatform,
  shotDriftWarning,
  shotEntries,
  shouldIgnoreWatchPath,
  watchChangePath,
} from "./visual-catalog.mjs";

const require = createRequire(import.meta.url);
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));

describe("createInactivityWatchdog", () => {
  it("measures inactivity from the latest progress event", () => {
    vi.useFakeTimers();
    try {
      const onTimeout = vi.fn();
      const watchdog = createInactivityWatchdog(onTimeout, 1000);

      vi.advanceTimersByTime(750);
      watchdog.reset();
      vi.advanceTimersByTime(750);
      expect(onTimeout).not.toHaveBeenCalled();

      vi.advanceTimersByTime(250);
      expect(onTimeout).toHaveBeenCalledOnce();
      watchdog.cancel();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("maestroFlowSummary", () => {
  it("folds sharded and unsharded result lines into pass/fail lists", () => {
    const output = [
      "[shard 2] [Passed] Connected app screens (1m 16s)",
      "[shard 1] [Failed] Recent gateways and reconnection (33s) (Assertion is false: \"Try again\" is visible)",
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

describe("newerRunStatus", () => {
  const now = Date.parse("2026-08-17T10:30:00.000Z");
  const server = {
    state: "ready",
    message: "Screenshots are up to date",
    updatedAt: "2026-08-17T10:00:00.000Z",
  };

  it("serves the file status when a capture wrote it more recently", () => {
    const file = {
      state: "capturing",
      message: "Running 7 flows",
      updatedAt: "2026-08-17T10:20:00.000Z",
    };
    expect(newerRunStatus(server, file, now)).toBe(file);
  });

  it("keeps the server status when the file is older or absent", () => {
    const file = { state: "ready", updatedAt: "2026-08-17T09:00:00.000Z" };
    expect(newerRunStatus(server, file, now)).toBe(server);
    expect(newerRunStatus(server, null, now)).toBe(server);
  });

  it("ignores a capturing entry a hard-killed run left behind", () => {
    const file = {
      state: "capturing",
      message: "Running 7 flows",
      updatedAt: "2026-08-17T09:30:00.000Z",
    };
    const muchLater = Date.parse("2026-08-17T11:00:00.000Z");
    expect(newerRunStatus(server, file, muchLater)).toBe(server);
  });
});

describe("gentleSpawnPlan", () => {
  it.each([
    ["off", false, "darwin", "xcodebuild", ["build"]],
    ["non-darwin", true, "linux", "gradle", ["assembleRelease"]],
  ])("passes commands through when %s", (_name, gentle, platform, command, args) => {
    expect(gentleSpawnPlan(command, args, gentle, platform)).toEqual({
      command,
      argumentsList: args,
    });
  });

  it("wraps the command at utility QoS when gentle on macOS", () => {
    expect(gentleSpawnPlan("maestro", ["test", "flow.yml"], true, "darwin")).toEqual({
      command: "taskpolicy",
      argumentsList: ["-c", "utility", "maestro", "test", "flow.yml"],
    });
  });
});

describe("assignFlowsToShards", () => {
  it("balances manifest-ordered flows across persistent simulators", () => {
    expect(
      assignFlowsToShards(
        ["connected", "connect", "home-empty", "recent", "error", "empty"],
        2,
      ),
    ).toEqual([
      ["connected", "home-empty", "error"],
      ["connect", "recent", "empty"],
    ]);
  });

  it("rejects an invalid shard count", () => {
    expect(() => assignFlowsToShards(["connected"], 0)).toThrow(
      "At least one Maestro shard is required.",
    );
  });
});

describe("continuousShardFlow", () => {
  it("combines independent flow commands into one continuous shard", () => {
    const flow = continuousShardFlow("com.vesta.visual", 1, [
      {
        label: "first.yml",
        source: "appId: ${APP_ID}\nname: First\n---\n- clearState\n",
      },
      {
        label: "second.yml",
        source: "appId: ${APP_ID}\nname: Second\n---\n- stopApp\n",
      },
    ]);

    expect(flow).toContain("appId: com.vesta.visual");
    expect(flow).toContain("name: Vesta visual catalog shard 1");
    expect(flow).toContain("- clearState\n\n- stopApp");
    expect(flow.match(/^---$/gm)).toHaveLength(1);
  });

  it("rejects a malformed source flow", () => {
    expect(() =>
      continuousShardFlow("com.vesta.visual", 1, [
        { label: "broken.yml", source: "appId: broken" },
      ]),
    ).toThrow("Maestro flow is missing ---: broken.yml");
  });
});

describe("createMaestroFailureParser", () => {
  it("reports only new failures and resets between continuous runs", () => {
    const onFailure = vi.fn();
    const parser = createMaestroFailureParser(onFailure);

    parser.consume("Flow output ❌ Tap connect\n");
    parser.consume("Waiting for changes…\n");
    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onFailure).toHaveBeenLastCalledWith("Tap connect");

    parser.beginRun();
    parser.consume("Running flow\n");
    expect(onFailure).toHaveBeenCalledTimes(1);
    parser.consume("Flow FAIL");
    parser.consume("ED\n");
    expect(onFailure).toHaveBeenCalledTimes(2);
    expect(onFailure).toHaveBeenLastCalledWith("Flow FAILED");
  });
});

describe("shouldIgnoreWatchPath", () => {
  it("ignores editor, snapshot, and test artifacts", () => {
    expect(shouldIgnoreWatchPath("/repo/mobile/src/view.test.tsx")).toBe(true);
    expect(shouldIgnoreWatchPath("/repo/mobile/src/__tests__/view.tsx")).toBe(
      true,
    );
    expect(shouldIgnoreWatchPath("/repo/mobile/src/.cache/view.tsx")).toBe(
      true,
    );
    expect(
      shouldIgnoreWatchPath("/repo/mobile/src/view.tsx.tmp.5218.abc123"),
    ).toBe(true);
    expect(shouldIgnoreWatchPath("/repo/mobile/src/view.tsx.tmp")).toBe(true);
    expect(shouldIgnoreWatchPath("/repo/mobile/src/view.tsx")).toBe(false);
  });
});

describe("watchChangePath", () => {
  it("attributes an atomic-save temporary event to its watched target", () => {
    expect(
      watchChangePath(
        "/repo/mobile/src",
        "/repo/mobile/src/view.tsx.tmp.5218.abc123",
      ),
    ).toBe("/repo/mobile/src");
    expect(
      watchChangePath("/repo/mobile/src", "/repo/mobile/src/view.tsx"),
    ).toBe("/repo/mobile/src/view.tsx");
  });
});

const registryScenarios = [
  {
    id: "connect",
    title: "Connect",
    description: "Connection actions",
    group: "Onboarding",
    screenshot: "connect.png",
  },
  {
    id: "recent-gateways",
    title: "Recent gateways",
    description: "Second onboarding state",
    group: "Onboarding",
    screenshot: "recent-gateways.png",
  },
  {
    id: "privacy-locked",
    title: "Privacy locked",
    description: "Privacy state",
    group: "Privacy",
    screenshot: "privacy-locked.png",
  },
  {
    id: "provider",
    title: "Provider and model",
    description: "Provider settings",
    group: "Agent settings",
    screenshot: "provider.png",
    platforms: ["ios"],
  },
];
const registryShots = {
  ios: {
    "connect.png": {
      src: "shots/ios/connect.png",
      mtime: 1111,
      size: { width: 603, height: 1311 },
    },
    "provider.png": { src: "shots/ios/provider.png", mtime: 2222 },
  },
  android: {
    "connect.png": { src: "shots/android/connect.png", mtime: 3333 },
  },
};

describe("shotDriftWarning", () => {
  const manifest = {
    scenarios: [{ screenshot: "connect.png" }, { screenshot: "privacy.png" }],
  };

  it("is empty when the produced shots match the registry", () => {
    expect(
      shotDriftWarning(new Set(["connect.png", "privacy.png"]), manifest),
    ).toBe("");
  });

  it("names missing and unexpected shots without refusing the run", () => {
    expect(shotDriftWarning(new Set(["connect.png", "stray.png"]), manifest)).toBe(
      "missing: privacy.png; unexpected: stray.png",
    );
  });
});

describe("galleryView", () => {
  const view = galleryView(registryScenarios, registryShots);

  it("renders both platform slots for every registry scenario", () => {
    expect(view.scenarios).toHaveLength(registryScenarios.length);
    for (const scenario of view.scenarios) {
      expect(scenario.slots.map((slot) => slot.label)).toEqual([
        "iOS",
        "Android",
      ]);
    }
  });

  it("fills a captured slot from its shot file entry", () => {
    const connect = view.scenarios[0];
    expect(connect.slots[0]).toMatchObject({
      state: "captured",
      src: "shots/ios/connect.png",
      mtime: 1111,
      size: { width: 603, height: 1311 },
    });
    expect(connect.slots[1]).toMatchObject({
      state: "captured",
      src: "shots/android/connect.png",
    });
  });

  it("marks a missing shot file and a platform-excluded scenario apart", () => {
    const recent = view.scenarios[1];
    expect(recent.slots[0]).toMatchObject({
      state: "missing",
      note: "Not captured yet",
    });

    const provider = view.scenarios[3];
    expect(provider.slots[0].state).toBe("captured");
    expect(provider.slots[1]).toMatchObject({
      state: "excluded",
      note: "iOS only",
    });
  });
});

describe("galleryHtml", () => {
  const view = galleryView(registryScenarios, registryShots, {
    git: { revision: "abc123", dirty: true },
    reports: [{ label: "iOS Maestro report", href: "maestro/report.html" }],
  });
  const html = galleryHtml(view);

  it("renders side-by-side platform slots with their labels and notes", () => {
    expect(html).toContain('data-platforms="2"');
    expect(html).toContain(">iOS</span>");
    expect(html).toContain(">Android</span>");
    expect(html).toContain(">Not captured yet</span>");
    expect(html).toContain(">iOS only</span>");
  });

  it("stamps captured images with their file mtime for cache busting", () => {
    expect(html).toContain('src="shots/ios/connect.png?v=1111"');
    expect(html).toContain('src="shots/android/connect.png?v=3333"');
    expect(html).toContain('style="--shot-ratio: 603 / 1311"');
  });

  it("groups screenshots into registry-ordered sections", () => {
    expect(html.match(/class="scenario-section"/g)).toHaveLength(3);
    expect(html).toContain(">2 screens</span>");
    expect(html.indexOf(">Onboarding<")).toBeLessThan(
      html.indexOf(">Privacy<"),
    );
  });

  it("links only the Maestro reports that exist", () => {
    expect(html).toContain('href="maestro/report.html"');
    expect(html).not.toContain('href="android/maestro/report.html"');
    expect(galleryHtml(galleryView(registryScenarios, registryShots))).not.toContain(
      "Maestro report",
    );
  });

  it("annotates each shot for the shots.json poll and copy references", () => {
    expect(html).toContain('data-screenshot="connect.png"');
    expect(html).toContain('data-platform="ios"');
    expect(html).toContain('data-platform="android"');
    expect(html).toContain('data-state="excluded"');
    expect(html).toContain('data-scenario-id="connect"');
    expect(html).toContain('data-title="Connect"');
    expect(html).toContain('data-revision="abc123"');
    expect(html).toContain('class="copy-ref"');
    expect(html).toContain("visual-ref: ");
    expect(html).toContain('fetch("shots.json"');
    expect(html).not.toContain("live.json");
    expect(html).not.toContain("catalog.json");
  });

  it("renders a scan row per platform with its trigger", () => {
    expect(html).toContain('class="scan-row" data-platform="ios"');
    expect(html).toContain('class="scan-row" data-platform="android"');
    expect(html).toContain('"capture/" + button.closest(".scan-row").dataset.platform');
  });

  it("emits an inline script that parses", () => {
    const open = "<scr" + "ipt>";
    const start = html.lastIndexOf(open) + open.length;
    const end = html.lastIndexOf("</scr" + "ipt>");
    const body = html.slice(start, end);
    expect(body.length).toBeGreaterThan(0);
    expect(() => new Function(body)).not.toThrow();
  });
});

describe("shotEntries", () => {
  it("indexes shot files per platform with gallery-relative sources", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-shots-"));
    await mkdir(path.join(base, "shots/ios"), { recursive: true });
    await mkdir(path.join(base, "shots/android"), { recursive: true });
    await writeFile(path.join(base, "shots/ios/connect.png"), "ios-shot");
    await writeFile(path.join(base, "shots/ios/notes.txt"), "ignored");
    await writeFile(path.join(base, "shots/android/connect.png"), "android-shot");

    const entries = await shotEntries(base);

    expect(entries.ios["connect.png"].src).toBe("shots/ios/connect.png");
    expect(entries.ios["connect.png"].mtime).toBeGreaterThan(0);
    expect(entries.ios["notes.txt"]).toBeUndefined();
    expect(entries.android["connect.png"].src).toBe(
      "shots/android/connect.png",
    );
  });

  it("serves empty platforms while the shots directories do not exist", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-shots-"));
    expect(await shotEntries(base)).toEqual({ ios: {}, android: {} });
  });
});

describe("loadManifest", () => {
  it("serves every scenario on both platforms now that no state is iOS-only", async () => {
    const iosManifest = await loadManifest("ios");
    expect(iosManifest.scenarios).toHaveLength(iosManifest.allScenarios.length);

    const androidManifest = await loadManifest("android");
    const excluded = androidManifest.allScenarios
      .filter((scenario) => !scenarioOnPlatform(scenario, "android"))
      .map((scenario) => scenario.id);
    expect(excluded).toEqual([]);
    expect(androidManifest.scenarios).toHaveLength(
      androidManifest.allScenarios.length,
    );
  });
});

describe("visual Metro privacy override", () => {
  it("only intercepts the production privacy-provider consumers", () => {
    const config = require("../visual/metro.config.js");
    const fallback = vi.fn(() => ({ type: "empty" }));
    const context = {
      originModulePath: path.resolve(scriptDirectory, "../src/other/view.tsx"),
      resolveRequest: fallback,
    };

    expect(
      config.resolver.resolveRequest(context, "./privacy-provider", "ios"),
    ).toEqual({ type: "empty" });
    expect(fallback).toHaveBeenCalledOnce();

    const privacyContext = {
      ...context,
      originModulePath: path.resolve(
        scriptDirectory,
        "../src/privacy/privacy-gate.tsx",
      ),
    };
    const resolution = config.resolver.resolveRequest(
      privacyContext,
      "./privacy-provider",
      "ios",
    );
    expect(resolution.type).toBe("sourceFile");
    expect(resolution.filePath).toBe(
      path.resolve(scriptDirectory, "../visual/harness/privacy-provider.tsx"),
    );
    expect(fallback).toHaveBeenCalledOnce();
  });
});

describe("visual Metro agent fixtures", () => {
  it("substitutes the seeded agent-holds fixture for every consumer", () => {
    const config = require("../visual/metro.config.js");
    const fallback = vi.fn(() => ({ type: "empty" }));
    const fixture = path.resolve(
      scriptDirectory,
      "../visual/harness/agent-holds-provider.tsx",
    );

    for (const origin of ["../app/_layout.tsx", "../src/chat/useAgentSocket.ts"]) {
      expect(
        config.resolver.resolveRequest(
          {
            originModulePath: path.resolve(scriptDirectory, origin),
            resolveRequest: fallback,
          },
          "@/holds/AgentHoldsProvider",
          "ios",
        ),
      ).toEqual({ type: "sourceFile", filePath: fixture });
    }
    expect(fallback).not.toHaveBeenCalled();
  });

  it("substitutes deterministic dashboard content outside production code", () => {
    const config = require("../visual/metro.config.js");
    const fallback = vi.fn(() => ({ type: "empty" }));
    const resolution = config.resolver.resolveRequest(
      {
        originModulePath: path.resolve(
          scriptDirectory,
          "../src/agent/DashboardPage.tsx",
        ),
        resolveRequest: fallback,
      },
      "@/components/DashboardWebView",
      "ios",
    );

    expect(resolution).toEqual({
      type: "sourceFile",
      filePath: path.resolve(
        scriptDirectory,
        "../visual/harness/dashboard-web-view.tsx",
      ),
    });
    expect(fallback).not.toHaveBeenCalled();
  });
});
