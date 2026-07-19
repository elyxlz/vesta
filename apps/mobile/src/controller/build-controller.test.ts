import { describe, expect, it, vi } from "vitest";
import type { ControllerDeps } from "@vesta/core";
import type { ConnectionConfig } from "@/api/types";
import { buildController, type ControllerSession } from "./build-controller";

const captured = vi.hoisted(() => ({ deps: null as ControllerDeps | null }));

vi.mock("@vesta/core", () => ({
  createController: (deps: ControllerDeps) => {
    captured.deps = deps;
    return { close: vi.fn() };
  },
}));

function fakeConnection(overrides: Partial<ConnectionConfig> = {}): ConnectionConfig {
  return {
    url: "https://gateway.test",
    accessToken: "tok en",
    refreshToken: "refresh",
    expiresAt: 0,
    hosted: false,
    ...overrides,
  };
}

function deps(): ControllerDeps {
  const value = captured.deps;
  if (!value) throw new Error("createController was not called");
  return value;
}

describe("buildController", () => {
  it("builds the /sync URL over ws with an encoded token", () => {
    buildController({
      getConnection: () => fakeConnection(),
      refreshAccessToken: vi.fn(),
    });

    expect(deps().sync.buildUrl()).toBe(
      "wss://gateway.test/sync?token=tok%20en",
    );
  });

  it("exposes the connection base URL and token to the http client", () => {
    buildController({
      getConnection: () => fakeConnection(),
      refreshAccessToken: vi.fn(),
    });

    expect(deps().http.baseUrl).toBe("https://gateway.test");
    expect(deps().http.token()).toBe("tok en");
  });

  it("reads the connection live so a rotated token flows to the sync URL", () => {
    let current = fakeConnection({ accessToken: "old" });
    buildController({
      getConnection: () => current,
      refreshAccessToken: vi.fn(),
    });

    expect(deps().http.token()).toBe("old");
    current = fakeConnection({ accessToken: "new" });
    expect(deps().http.token()).toBe("new");
    expect(deps().sync.buildUrl()).toBe("wss://gateway.test/sync?token=new");
  });

  it("delegates http refresh to the session's refreshAccessToken", async () => {
    const refreshAccessToken = vi.fn<ControllerSession["refreshAccessToken"]>(
      () => Promise.resolve(true),
    );
    buildController({ getConnection: () => fakeConnection(), refreshAccessToken });

    await expect(deps().http.refresh()).resolves.toBe(true);
    expect(refreshAccessToken).toHaveBeenCalledOnce();
  });

  it("throws when building the sync URL without a connection", () => {
    buildController({ getConnection: () => null, refreshAccessToken: vi.fn() });

    expect(() => deps().sync.buildUrl()).toThrow(
      "not connected to a Vesta gateway",
    );
    expect(deps().http.token()).toBeNull();
  });
});
