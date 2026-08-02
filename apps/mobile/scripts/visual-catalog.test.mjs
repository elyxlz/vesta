import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import {
  createInactivityWatchdog,
  createMaestroFailureParser,
  galleryHtml,
  shouldIgnoreWatchPath,
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
    expect(shouldIgnoreWatchPath("/repo/mobile/src/view.tsx")).toBe(false);
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
  it("uses one chat hold fixture for both provider import paths", () => {
    const config = require("../visual/metro.config.js");
    const fallback = vi.fn(() => ({ type: "empty" }));
    const fixture = path.resolve(
      scriptDirectory,
      "../visual/harness/chat-hold-provider.tsx",
    );

    expect(
      config.resolver.resolveRequest(
        {
          originModulePath: path.resolve(scriptDirectory, "../app/_layout.tsx"),
          resolveRequest: fallback,
        },
        "@/chat/ChatHoldProvider",
        "ios",
      ),
    ).toEqual({ type: "sourceFile", filePath: fixture });
    expect(
      config.resolver.resolveRequest(
        {
          originModulePath: path.resolve(
            scriptDirectory,
            "../src/chat/useAgentSocket.ts",
          ),
          resolveRequest: fallback,
        },
        "./ChatHoldProvider",
        "ios",
      ),
    ).toEqual({ type: "sourceFile", filePath: fixture });
    expect(fallback).not.toHaveBeenCalled();
  });
});
