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

// The api client owns token stamping and the refresh pre-flight (see client.test.ts); here it is
// only the path buildController hands it that matters.
function fakeWebsocketUrl(path: string): Promise<string> {
  return Promise.resolve(`wss://gateway.test${path}?token=tok`);
}

function deps(): ControllerDeps {
  const value = captured.deps;
  if (!value) throw new Error("createController was not called");
  return value;
}

describe("buildController", () => {
  it("asks the session's builder for the /sync URL", async () => {
    const websocketUrl = vi.fn(fakeWebsocketUrl);
    buildController({
      getConnection: () => fakeConnection(),
      refreshAccessToken: vi.fn(),
      websocketUrl,
    });

    await expect(deps().sync.buildUrl()).resolves.toBe(
      "wss://gateway.test/sync?token=tok",
    );
    expect(websocketUrl).toHaveBeenCalledWith("/sync");
  });

  it("exposes the connection base URL and token to the http client", () => {
    buildController({
      getConnection: () => fakeConnection(),
      refreshAccessToken: vi.fn(),
      websocketUrl: fakeWebsocketUrl,
    });

    expect(deps().http.baseUrl()).toBe("https://gateway.test");
    expect(deps().http.token()).toBe("tok en");
  });

  it("reads the connection live so a rotated token reaches the http client", () => {
    let current = fakeConnection({ accessToken: "old" });
    buildController({
      getConnection: () => current,
      refreshAccessToken: vi.fn(),
      websocketUrl: fakeWebsocketUrl,
    });

    expect(deps().http.token()).toBe("old");
    current = fakeConnection({ accessToken: "new" });
    expect(deps().http.token()).toBe("new");
  });

  it("delegates http refresh to the session's refreshAccessToken", async () => {
    const refreshAccessToken = vi.fn<ControllerSession["refreshAccessToken"]>(
      () => Promise.resolve(true),
    );
    buildController({
      getConnection: () => fakeConnection(),
      refreshAccessToken,
      websocketUrl: fakeWebsocketUrl,
    });

    await expect(deps().http.refresh()).resolves.toBe(true);
    expect(refreshAccessToken).toHaveBeenCalledOnce();
  });

  it("passes the client version through to the sync socket for the drift check", () => {
    buildController(
      {
        getConnection: () => fakeConnection(),
        refreshAccessToken: vi.fn(),
        websocketUrl: fakeWebsocketUrl,
      },
      "0.1.179",
    );

    expect(deps().sync.clientVersion).toBe("0.1.179");
  });

  it("reports no token to the http client without a connection", () => {
    buildController({
      getConnection: () => null,
      refreshAccessToken: vi.fn(),
      websocketUrl: fakeWebsocketUrl,
    });

    expect(deps().http.token()).toBeNull();
  });
});
