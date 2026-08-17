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
  gentleSpawnPlan,
  maestroFlowSummary,
  newerRunStatus,
  liveCaptureEntries,
  loadManifest,
  scenarioOnPlatform,
  shouldIgnoreWatchPath,
  unifiedCatalog,
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

describe("galleryHtml", () => {
  const catalog = {
    generatedAt: "2026-07-31T12:00:00.000Z",
    reportAvailable: false,
    device: { name: "2 × iPhone 17", runtime: "iOS 26.4" },
    git: { revision: "abc123", dirty: true },
    scenarios: [],
  };

  it("only links a Maestro report produced by the current mode", () => {
    expect(galleryHtml(catalog)).not.toContain("Maestro report");
    expect(galleryHtml({ ...catalog, reportAvailable: true })).toContain(
      "Maestro report",
    );
  });

  it("relies on the device chrome already present in captured screenshots", () => {
    const html = galleryHtml({
      ...catalog,
      scenarios: [
        {
          captured: true,
          description: "Connection actions",
          group: "Onboarding",
          image: "screenshots/connect-actions.png",
          size: { width: 603, height: 1311 },
          title: "Connect",
        },
      ],
    });

    expect(html).toContain('src="screenshots/connect-actions.png"');
    expect(html).not.toContain("dynamic-island");
  });

  it("labels an uncaptured scenario with its platform note", () => {
    const html = galleryHtml({
      ...catalog,
      scenarios: [
        {
          captured: false,
          description: "Provider settings",
          group: "Agent settings",
          image: "",
          missingLabel: "iOS only",
          title: "Provider and model",
        },
      ],
    });

    expect(html).toContain(">iOS only</span>");
    expect(html).not.toContain("Screenshot missing");
  });

  it("groups screenshots into manifest-ordered sections without search", () => {
    const html = galleryHtml({
      ...catalog,
      scenarios: [
        {
          captured: true,
          description: "First onboarding state",
          group: "Onboarding",
          image: "screenshots/connect.png",
          title: "Connect",
        },
        {
          captured: true,
          description: "Privacy state",
          group: "Privacy",
          image: "screenshots/privacy.png",
          title: "Privacy",
        },
        {
          captured: true,
          description: "Second onboarding state",
          group: "Onboarding",
          image: "screenshots/recent.png",
          title: "Recent gateways",
        },
      ],
    });

    expect(html.match(/class="scenario-section"/g)).toHaveLength(2);
    expect(html).toContain(">2 screens</span>");
    expect(html.indexOf(">Onboarding<")).toBeLessThan(
      html.indexOf(">Privacy<"),
    );
    expect(html).not.toContain('type="search"');
    expect(html).not.toContain('querySelector("#filter")');
  });
});

describe("unifiedCatalog", () => {
  const iosCatalog = {
    generatedAt: "2026-08-06T21:00:00.000Z",
    reportAvailable: true,
    device: { name: "2 × iPhone 17", runtime: "iOS 26.4" },
    git: { revision: "abc123", dirty: false },
    scenarios: [
      {
        id: "connect",
        captured: true,
        description: "Connection actions",
        group: "Onboarding",
        image: "screenshots/1/connect.png",
        size: { width: 603, height: 1311 },
        title: "Connect",
      },
    ],
  };
  const androidCatalog = {
    generatedAt: "2026-08-16T15:00:00.000Z",
    platform: "android",
    reportAvailable: true,
    device: { name: "vesta-visual (Android emulator)", runtime: "Android 16" },
    git: { revision: "def456", dirty: false },
    scenarios: [
      {
        id: "connect",
        captured: true,
        description: "Connection actions",
        group: "Onboarding",
        image: "screenshots/2/connect.png",
        size: { width: 540, height: 1200 },
        title: "Connect",
      },
      {
        id: "privacy-locked",
        captured: true,
        description: "Privacy lock",
        group: "Privacy",
        image: "screenshots/2/privacy-locked.png",
        size: { width: 540, height: 1200 },
        title: "Privacy locked",
      },
    ],
  };

  it("passes a single catalog through unchanged", () => {
    expect(unifiedCatalog(iosCatalog, null)).toBe(iosCatalog);
    expect(unifiedCatalog(null, androidCatalog)).toBe(androidCatalog);
    expect(unifiedCatalog(null, null)).toBeNull();
  });

  it("pairs both platform captures per scenario and prefixes Android images", () => {
    const merged = unifiedCatalog(iosCatalog, androidCatalog);

    const connect = merged.scenarios[0];
    expect(connect.captures.map((capture) => capture.platform)).toEqual([
      "iOS",
      "Android",
    ]);
    expect(connect.captures[0].image).toBe("screenshots/1/connect.png");
    expect(connect.captures[1].image).toBe("android/screenshots/2/connect.png");
    expect(merged.generatedAt).toBe(androidCatalog.generatedAt);
    expect(merged.git.revision).toBe("def456");
  });

  it("marks a scenario one platform has not captured yet", () => {
    const merged = unifiedCatalog(iosCatalog, androidCatalog);

    const privacy = merged.scenarios[1];
    expect(privacy.id).toBe("privacy-locked");
    expect(privacy.captures[0]).toMatchObject({
      platform: "iOS",
      captured: false,
      missingLabel: "Not captured yet",
    });
    expect(privacy.captures[1].captured).toBe(true);
  });

  it("renders side-by-side shots with platform tags and both reports", () => {
    const html = galleryHtml(unifiedCatalog(iosCatalog, androidCatalog));

    expect(html).toContain('data-platforms="2"');
    expect(html).toContain(">iOS</span>");
    expect(html).toContain(">Android</span>");
    expect(html).toContain('src="android/screenshots/2/connect.png"');
    expect(html).toContain('href="maestro/report.html"');
    expect(html).toContain('href="android/maestro/report.html"');
    expect(html).toContain("iOS · 2 × iPhone 17 · iOS 26.4");
    expect(html).toContain("Android · vesta-visual (Android emulator) · Android 16");
  });

  it("annotates each shot for the live-capture poll", () => {
    const iosOnly = {
      ...androidCatalog,
      scenarios: [
        androidCatalog.scenarios[0],
        {
          id: "provider",
          screenshot: "provider.png",
          captured: false,
          expected: false,
          description: "Provider settings",
          group: "Agent settings",
          image: "",
          missingLabel: "iOS only",
          title: "Provider",
        },
      ],
    };
    const html = galleryHtml(
      unifiedCatalog(
        {
          ...iosCatalog,
          scenarios: iosCatalog.scenarios.map((scenario) => ({
            ...scenario,
            screenshot: "connect.png",
          })),
        },
        iosOnly,
      ),
    );

    expect(html).toContain('data-screenshot="connect.png"');
    expect(html).toContain('data-live-platform="ios"');
    expect(html).toContain('data-live-platform="android"');
    expect(html).toContain('data-expected="false"');
    expect(html).toContain('fetch("live.json"');
    expect(html).toContain('data-scenario-id="connect"');
    expect(html).toContain('data-title="Connect"');
    expect(html).toContain('class="copy-ref"');
    expect(html).toContain("visual-ref: ");
  });

  it("emits an inline script that parses", () => {
    const html = galleryHtml(unifiedCatalog(iosCatalog, androidCatalog));
    const open = "<scr" + "ipt>";
    const start = html.lastIndexOf(open) + open.length;
    const end = html.lastIndexOf("</scr" + "ipt>");
    const body = html.slice(start, end);
    expect(body.length).toBeGreaterThan(0);
    expect(() => new Function(body)).not.toThrow();
  });

  it("renders a scan row per platform with its last-scan stamp and trigger", () => {
    const merged = galleryHtml(unifiedCatalog(iosCatalog, androidCatalog));
    expect(merged).toContain('class="scan-row" data-platform="ios"');
    expect(merged).toContain('class="scan-row" data-platform="android"');
    expect(merged).toContain(`data-generated-at="${iosCatalog.generatedAt}"`);
    expect(merged).toContain(
      `data-generated-at="${androidCatalog.generatedAt}"`,
    );
    expect(merged).toContain('"capture/" + row.dataset.platform');

    const single = galleryHtml({ ...iosCatalog, scenarios: [] });
    expect(single).toContain('class="scan-row" data-platform="ios"');
    expect(single).not.toContain('class="scan-row" data-platform="android"');
  });
});

describe("liveCaptureEntries", () => {
  it("indexes flat and maestro capture files by newest per platform", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-live-"));
    const flat = path.join(base, "watch/screenshots");
    const maestro = path.join(base, "android/maestro/flow-1/takeScreenshot");
    await mkdir(flat, { recursive: true });
    await mkdir(maestro, { recursive: true });
    await writeFile(path.join(flat, "connect.png"), "ios-shot");
    await writeFile(path.join(flat, "notes.txt"), "ignored");
    await writeFile(path.join(maestro, "connect.png"), "android-shot");

    const entries = await liveCaptureEntries(
      [
        { platform: "ios", directory: flat },
        { platform: "ios", directory: path.join(base, "missing") },
        {
          platform: "android",
          directory: path.join(base, "android/maestro"),
          maestro: true,
        },
      ],
      base,
    );

    expect(entries.ios["connect.png"].src).toBe("watch/screenshots/connect.png");
    expect(entries.ios["connect.png"].mtime).toBeGreaterThan(0);
    expect(entries.ios["notes.txt"]).toBeUndefined();
    expect(entries.android["connect.png"].src).toBe(
      "android/maestro/flow-1/takeScreenshot/connect.png",
    );
  });

  it("contains a root that fails mid-scan instead of throwing", async () => {
    const base = await mkdtemp(path.join(os.tmpdir(), "visual-live-"));
    const flat = path.join(base, "shots");
    await mkdir(flat, { recursive: true });
    await writeFile(path.join(flat, "connect.png"), "shot");
    const notADirectory = path.join(base, "not-a-directory");
    await writeFile(notADirectory, "capture is rewriting this");

    const entries = await liveCaptureEntries(
      [
        { platform: "android", directory: notADirectory, maestro: true },
        { platform: "ios", directory: flat },
      ],
      base,
    );

    expect(entries.ios["connect.png"].src).toBe("shots/connect.png");
    expect(entries.android).toEqual({});
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
