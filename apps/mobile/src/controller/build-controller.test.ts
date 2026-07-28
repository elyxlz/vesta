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
  it("builds the /sync URL over ws with an encoded token", async () => {
    buildController({
      getConnection: () => fakeConnection(),
      refreshAccessToken: vi.fn(),
    });

    await expect(deps().sync.buildUrl()).resolves.toBe(
      "wss://gateway.test/sync?token=tok%20en",
    );
  });

  it("exposes the connection base URL and token to the http client", () => {
    buildController({
      getConnection: () => fakeConnection(),
      refreshAccessToken: vi.fn(),
    });

    expect(deps().http.baseUrl()).toBe("https://gateway.test");
    expect(deps().http.token()).toBe("tok en");
  });

  it("reads the connection live so a rotated token flows to the sync URL", async () => {
    let current = fakeConnection({ accessToken: "old" });
    buildController({
      getConnection: () => current,
      refreshAccessToken: vi.fn(),
    });

    expect(deps().http.token()).toBe("old");
    current = fakeConnection({ accessToken: "new" });
    expect(deps().http.token()).toBe("new");
    await expect(deps().sync.buildUrl()).resolves.toBe(
      "wss://gateway.test/sync?token=new",
    );
  });

  it("delegates http refresh to the session's refreshAccessToken", async () => {
    const refreshAccessToken = vi.fn<ControllerSession["refreshAccessToken"]>(
      () => Promise.resolve(true),
    );
    buildController({ getConnection: () => fakeConnection(), refreshAccessToken });

    await expect(deps().http.refresh()).resolves.toBe(true);
    expect(refreshAccessToken).toHaveBeenCalledOnce();
  });

  it("passes the client version through to the sync socket for the drift check", () => {
    buildController(
      { getConnection: () => fakeConnection(), refreshAccessToken: vi.fn() },
      "0.1.179",
    );

    expect(deps().sync.clientVersion).toBe("0.1.179");
  });

  it("rejects when building the sync URL without a connection", async () => {
    buildController({ getConnection: () => null, refreshAccessToken: vi.fn() });

    await expect(deps().sync.buildUrl()).rejects.toThrow(
      "not connected to a Vesta gateway",
    );
    expect(deps().http.token()).toBeNull();
  });

  it("rotates an expiring token before handing out the sync URL", async () => {
    // Every connect goes through the builder, so a client returning after a long background
    // never presents the token that expired while it was away.
    let current = fakeConnection({ accessToken: "stale", expiresAt: 0 });
    const refreshAccessToken = vi.fn(() => {
      current = fakeConnection({ accessToken: "rotated", expiresAt: Date.now() + 3_600_000 });
      return Promise.resolve(true);
    });
    buildController({ getConnection: () => current, refreshAccessToken });

    await expect(deps().sync.buildUrl()).resolves.toBe(
      "wss://gateway.test/sync?token=rotated",
    );
    expect(refreshAccessToken).toHaveBeenCalledOnce();
  });

  it("leaves a fresh token alone", async () => {
    const refreshAccessToken = vi.fn(() => Promise.resolve(true));
    buildController({
      getConnection: () => fakeConnection({ expiresAt: Date.now() + 3_600_000 }),
      refreshAccessToken,
    });

    await deps().sync.buildUrl();
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });
});
