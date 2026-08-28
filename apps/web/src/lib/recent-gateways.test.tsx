// Exercises localStorage, so it runs in the jsdom project (.test.tsx include).
import { afterEach, describe, expect, it } from "vitest";
import type { ConnectionConfig } from "@/lib/connection";
import {
  forgetRecentGateway,
  readRecentGateways,
  recentGatewayId,
  rememberGateway,
  removeRecentGateway,
  upsertRecentGateway,
  type RecentGateway,
} from "./recent-gateways";

function conn(
  url: string,
  over: Partial<ConnectionConfig> = {},
): ConnectionConfig {
  return {
    url,
    accessToken: "at",
    refreshToken: "rt",
    expiresAt: 123,
    ...over,
  };
}

afterEach(() => {
  localStorage.clear();
});

describe("recentGatewayId", () => {
  it("is stable across the same origin and differs across origins", () => {
    expect(recentGatewayId("https://box.example")).toBe(
      recentGatewayId("https://box.example/app"),
    );
    expect(recentGatewayId("https://box.example")).not.toBe(
      recentGatewayId("https://other.example"),
    );
  });
});

describe("upsertRecentGateway", () => {
  it("moves a touched gateway to the front and stamps the time", () => {
    const first = upsertRecentGateway(
      [],
      { connection: conn("https://a.example") },
      { touch: true, now: 10 },
    );
    const second = upsertRecentGateway(
      first,
      { connection: conn("https://b.example") },
      { touch: true, now: 20 },
    );
    const back = upsertRecentGateway(
      second,
      { connection: conn("https://a.example") },
      { touch: true, now: 30 },
    );
    expect(back.map((g) => g.url)).toEqual([
      "https://a.example",
      "https://b.example",
    ]);
    expect(back[0]?.lastConnectedAt).toBe(30);
  });

  it("preserves the connect key when a later save omits it", () => {
    const withKey = upsertRecentGateway(
      [],
      { connection: conn("https://a.example"), connectKey: "secret" },
      { touch: true, now: 10 },
    );
    const refreshed = upsertRecentGateway(
      withKey,
      { connection: conn("https://a.example", { accessToken: "new" }) },
      { touch: false, now: 20 },
    );
    expect(refreshed[0]?.connectKey).toBe("secret");
    expect(refreshed[0]?.connection.accessToken).toBe("new");
    expect(refreshed[0]?.lastConnectedAt).toBe(10);
  });

  it("dedups by origin so one record survives per gateway", () => {
    const once = upsertRecentGateway(
      [],
      { connection: conn("https://a.example") },
      { touch: true, now: 10 },
    );
    const twice = upsertRecentGateway(
      once,
      { connection: conn("https://a.example/app") },
      { touch: true, now: 20 },
    );
    expect(twice).toHaveLength(1);
  });
});

describe("removeRecentGateway", () => {
  it("drops the matching id", () => {
    const gateways: RecentGateway[] = upsertRecentGateway(
      [],
      { connection: conn("https://a.example") },
      { touch: true, now: 10 },
    );
    expect(
      removeRecentGateway(gateways, recentGatewayId("https://a.example")),
    ).toEqual([]);
  });
});

describe("localStorage round-trip", () => {
  it("remembers, reads back, and forgets a gateway", () => {
    rememberGateway(conn("https://a.example"), { connectKey: "k" });
    const read = readRecentGateways();
    expect(read).toHaveLength(1);
    expect(read[0]?.url).toBe("https://a.example");
    expect(read[0]?.connectKey).toBe("k");

    forgetRecentGateway(recentGatewayId("https://a.example"));
    expect(readRecentGateways()).toEqual([]);
  });

  it("drops invalid records and survives corrupt json", () => {
    localStorage.setItem(
      "vesta-recent-gateways",
      JSON.stringify([
        {
          url: "https://good.example",
          connection: conn("https://good.example"),
          lastConnectedAt: 1,
        },
        { url: "not-a-url", lastConnectedAt: 2 },
        { nonsense: true },
      ]),
    );
    expect(readRecentGateways().map((g) => g.url)).toEqual([
      "https://good.example",
    ]);

    localStorage.setItem("vesta-recent-gateways", "{ broken");
    expect(readRecentGateways()).toEqual([]);
  });
});
