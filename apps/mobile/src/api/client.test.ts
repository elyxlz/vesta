import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";
import type { ConnectionConfig } from "./types";

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
