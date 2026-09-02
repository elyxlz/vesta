import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";
import type { ConnectionConfig } from "@vesta/core";

const connection: ConnectionConfig = {
  url: "https://gateway.example",
  accessToken: "access-token",
  refreshToken: "refresh-token",
  expiresAt: Date.now() + 60 * 60 * 1000,
  hosted: false,
};

function createTestClient() {
  return createApiClient({
    getConnection: () => connection,
    onConnectionChange: async () => undefined,
    onSessionExpired: async () => undefined,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("API errors", () => {
  it("does not expose an HTML gateway error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<!doctype html><html>Cloudflare error</html>", {
          status: 502,
          statusText: "Bad Gateway",
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );

    await expect(
      createTestClient().request("/agents/test/logs"),
    ).rejects.toEqual(
      new ApiError(502, "Gateway request failed (502 Bad Gateway)."),
    );
  });

  it("keeps structured gateway error messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "Agent not found." }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      createTestClient().request("/agents/test/logs"),
    ).rejects.toEqual(new ApiError(404, "Agent not found."));
  });
});

describe("authenticated URLs", () => {
  it("stamps the token and swaps the scheme for a socket URL", async () => {
    await expect(createTestClient().websocketUrl("/sync")).resolves.toBe(
      "wss://gateway.example/sync?token=access-token",
    );
  });

  it("keeps caller query params alongside the token", async () => {
    await expect(
      createTestClient().websocketUrl(
        "/sync",
        new URLSearchParams({ resync: "true" }),
      ),
    ).resolves.toBe(
      "wss://gateway.example/sync?resync=true&token=access-token",
    );
  });

  it("rotates an expiring token before handing out a URL", async () => {
    // Every socket connect goes through here, so a client returning after a long background
    // never presents the token that expired while it was away.
    let current: ConnectionConfig = {
      ...connection,
      accessToken: "stale",
      expiresAt: 0,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            access_token: "rotated",
            refresh_token: "next",
            expires_in: 3600,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const client = createApiClient({
      getConnection: () => current,
      onConnectionChange: async (next) => {
        current = next;
      },
      onSessionExpired: async () => undefined,
    });

    await expect(client.websocketUrl("/sync")).resolves.toBe(
      "wss://gateway.example/sync?token=rotated",
    );
  });

  it("leaves a fresh token alone", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await createTestClient().websocketUrl("/sync");

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects without a connection", async () => {
    const client = createApiClient({
      getConnection: () => null,
      onConnectionChange: async () => undefined,
      onSessionExpired: async () => undefined,
    });

    await expect(client.websocketUrl("/sync")).rejects.toThrow(
      "not connected to a gateway",
    );
  });
});
