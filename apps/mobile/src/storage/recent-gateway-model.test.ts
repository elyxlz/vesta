import { describe, expect, it } from "vitest";
import type { ConnectionConfig } from "@/api/types";
import {
  recentGatewayId,
  removeRecentGateway,
  upsertRecentGateway,
} from "./recent-gateway-model";

const first: ConnectionConfig = {
  url: "https://first.vesta.run",
  accessToken: "access-1",
  refreshToken: "refresh-1",
  expiresAt: 1,
  hosted: false,
};
const second: ConnectionConfig = {
  ...first,
  url: "https://second.vesta.run",
  accessToken: "access-2",
};

describe("recent gateway model", () => {
  it("produces stable SecureStore-safe identifiers", () => {
    const id = recentGatewayId(first.url);
    expect(id).toBe(recentGatewayId(first.url));
    expect(id).not.toBe(recentGatewayId(second.url));
    expect(id).toMatch(/^[a-zA-Z0-9._-]+$/);
  });

  it("orders manually connected gateways by recency", () => {
    const one = upsertRecentGateway([], first, { touch: true, now: 10 });
    const two = upsertRecentGateway(one, second, { touch: true, now: 20 });
    const refreshed = upsertRecentGateway(two, first, {
      touch: true,
      now: 30,
    });

    expect(refreshed.map((gateway) => gateway.url)).toEqual([
      first.url,
      second.url,
    ]);
    expect(refreshed[0]?.lastConnectedAt).toBe(30);
  });

  it("updates credentials without changing displayed recency", () => {
    const one = upsertRecentGateway([], first, { touch: true, now: 10 });
    const two = upsertRecentGateway(one, second, { touch: true, now: 20 });
    const refreshed = upsertRecentGateway(two, first, {
      touch: false,
      now: 30,
    });

    expect(refreshed.map((gateway) => gateway.url)).toEqual([
      second.url,
      first.url,
    ]);
    expect(refreshed[1]?.lastConnectedAt).toBe(10);
  });

  it("permanently removes a selected gateway from the index", () => {
    const gateways = upsertRecentGateway(
      upsertRecentGateway([], first, { touch: true, now: 10 }),
      second,
      { touch: true, now: 20 },
    );

    expect(
      removeRecentGateway(gateways, recentGatewayId(second.url)).map(
        (gateway) => gateway.url,
      ),
    ).toEqual([first.url]);
  });
});
