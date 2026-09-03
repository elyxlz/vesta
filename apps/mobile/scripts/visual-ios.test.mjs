import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

const require = createRequire(import.meta.url);
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));

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
      "../visual/harness/agent-holds.ts",
    );

    for (const origin of [
      "../src/agent/ChatPage.tsx",
      "../src/chat/useAgentSocket.ts",
    ]) {
      expect(
        config.resolver.resolveRequest(
          {
            originModulePath: path.resolve(scriptDirectory, origin),
            resolveRequest: fallback,
          },
          "@/holds/agent-holds",
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
