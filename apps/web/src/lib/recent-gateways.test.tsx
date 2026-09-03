// Exercises localStorage, so it runs in the jsdom project (.test.tsx include).
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConnectionConfig } from "@/lib/connection";
import { getConnection, setConnection } from "./connection";
import { native } from "./native";
import { useCredentialStorage } from "@/stores/use-credential-storage";
import {
  forgetRecentGateway,
  readRecentGateways,
  recentGatewayId,
  rememberGateway,
  rememberGatewayAfterConnect,
  upsertRecentGateway,
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
  vi.restoreAllMocks();
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

  it("refreshes the connection without bumping lastConnectedAt on an untouched save", () => {
    const initial = upsertRecentGateway(
      [],
      { connection: conn("https://a.example") },
      { touch: true, now: 10 },
    );
    const refreshed = upsertRecentGateway(
      initial,
      { connection: conn("https://a.example", { accessToken: "new" }) },
      { touch: false, now: 20 },
    );
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

describe("localStorage round-trip", () => {
  it("remembers, reads back, and forgets a gateway", async () => {
    await rememberGateway(conn("https://a.example"));
    const read = await readRecentGateways();
    expect(read).toHaveLength(1);
    expect(read[0]?.url).toBe("https://a.example");

    await forgetRecentGateway(recentGatewayId("https://a.example"));
    expect(await readRecentGateways()).toEqual([]);
  });

  it("drops invalid records and survives corrupt json", async () => {
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
    expect((await readRecentGateways()).map((g) => g.url)).toEqual([
      "https://good.example",
    ]);

    localStorage.setItem("vesta-recent-gateways", "{ broken");
    expect(await readRecentGateways()).toEqual([]);
  });

  it("clears a store holding a non-list value so the garbage is gone next read", async () => {
    localStorage.setItem("vesta-recent-gateways", JSON.stringify({ a: 1 }));
    expect(await readRecentGateways()).toEqual([]);
    expect(localStorage.getItem("vesta-recent-gateways")).toBeNull();
  });
});

// A storage write failure is a warning, not a lost session: the active gateway
// and the recents list both survive a throwing localStorage or a rejecting
// Electron secure store, so a device that cannot persist still stays connected.
describe("storage-write failure survives", () => {
  // The connection store's write is deferred one promise hop (`persist` in
  // connection.ts), so its warning lands after exactly that many microtasks.
  const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

  it.each<[string, () => void]>([
    [
      "localStorage throws",
      () => {
        vi.spyOn(Storage.prototype, "setItem").mockImplementationOnce(() => {
          throw new Error("storage unavailable");
        });
      },
    ],
    [
      "an Electron-style write rejects",
      () => {
        vi.spyOn(native.connectionStore, "write").mockRejectedValueOnce(
          new Error("secure storage unavailable"),
        );
      },
    ],
  ])("keeps a connected session when %s", async (_name, breakStore) => {
    breakStore();

    expect(() =>
      setConnection("https://box.example/", "access", "refresh", 60),
    ).not.toThrow();
    expect(getConnection()).toMatchObject({
      url: "https://box.example",
      accessToken: "access",
      refreshToken: "refresh",
    });

    await settle();
    expect(useCredentialStorage.getState().writeError).toMatch(
      /^could not save the active gateway: /,
    );

    setConnection("https://box.example/", "access", "refresh", 60);
    await settle();
    expect(useCredentialStorage.getState().writeError).toBeNull();
  });

  it("does not fail a successful connection when saving recents throws", async () => {
    const warning = vi
      .spyOn(console, "warn")
      .mockImplementation(() => undefined);
    vi.spyOn(native.recentGatewayStore, "write").mockRejectedValueOnce(
      new Error("storage unavailable"),
    );

    await expect(
      rememberGatewayAfterConnect(conn("https://a.example")),
    ).resolves.toBeUndefined();
    expect(warning).toHaveBeenCalledWith(
      "could not save the recent gateway",
      expect.any(Error),
    );
  });
});
