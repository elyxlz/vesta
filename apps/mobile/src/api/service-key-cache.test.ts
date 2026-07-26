import { describe, expect, it } from "vitest";
import type { ApiClient } from "./client";
import { serviceKeyCacheFor } from "./service-key-cache";
import type { ConnectionConfig } from "./types";

function connectionAt(url: string): ConnectionConfig {
  return {
    url,
    accessToken: "access-token",
    refreshToken: "refresh-token",
    expiresAt: Date.now() + 60 * 60 * 1000,
    hosted: false,
  };
}

// A stub client rather than a real one: the cache only ever touches `json` and `getConnection`,
// so the rest of the surface stays unreachable and a call to it is a test bug, not a fallback.
// `gatewayUrls` is walked one entry per read, the last one repeating, which is how a mid-session
// gateway switch looks to the lazy accessor.
function stubClient(gatewayUrls: readonly string[]): {
  api: ApiClient;
  mintedPaths: string[];
} {
  const mintedPaths: string[] = [];
  let reads = 0;
  const unused = () => {
    throw new Error("the service key cache must not reach this");
  };
  const api: ApiClient = {
    request: () => Promise.reject(new Error("unused")),
    json: <ResponseBody>(path: string) => {
      mintedPaths.push(path);
      const minted = {
        id: `id-${String(mintedPaths.length)}`,
        key: `key-${String(mintedPaths.length)}`,
        expires_at: null,
      };
      return Promise.resolve(minted as ResponseBody);
    },
    jsonInit: unused,
    websocketUrl: unused,
    mediaUrl: unused,
    getConnection: () => {
      const url = gatewayUrls.at(Math.min(reads, gatewayUrls.length - 1));
      if (url === undefined) throw new Error("stub needs one gateway at least");
      reads += 1;
      return connectionAt(url);
    },
    forceRefresh: () => Promise.resolve(true),
  };
  return { api, mintedPaths };
}

describe("serviceKeyCacheFor", () => {
  it("hands the same client the same cache, and another client its own", () => {
    const first = stubClient(["https://gateway.example"]).api;
    const second = stubClient(["https://gateway.example"]).api;

    expect(serviceKeyCacheFor(first)).toBe(serviceKeyCacheFor(first));
    expect(serviceKeyCacheFor(second)).not.toBe(serviceKeyCacheFor(first));
  });

  // The client outlives a gateway switch, so the cache would happily serve the first gateway's
  // key at the second, which refuses it. The lazy gateway read is what makes that a miss.
  it("mints again after the client moves to another gateway", async () => {
    const { api, mintedPaths } = stubClient([
      "https://first.example",
      "https://second.example",
    ]);
    const cache = serviceKeyCacheFor(api);

    const atFirst = await cache.get("alpha", "dashboard");
    const atSecond = await cache.get("alpha", "dashboard");

    expect(mintedPaths).toEqual([
      "/agents/alpha/services/dashboard/keys",
      "/agents/alpha/services/dashboard/keys",
    ]);
    expect(atSecond).not.toBe(atFirst);
  });

  it("reuses a key while the gateway stays put", async () => {
    const { api, mintedPaths } = stubClient(["https://gateway.example"]);
    const cache = serviceKeyCacheFor(api);

    const first = await cache.get("alpha", "dashboard");
    const second = await cache.get("alpha", "dashboard");

    expect(mintedPaths).toHaveLength(1);
    expect(second).toBe(first);
  });
});
