import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConnectionConfig } from "@/api/types";
import { runReauthCheck } from "./reauth-poll";

const FIVE_MIN_MS = 5 * 60 * 1000;

function fakeConnection(overrides: Partial<ConnectionConfig> = {}): ConnectionConfig {
  return {
    url: "https://gateway.test",
    accessToken: "tok",
    refreshToken: "refresh",
    expiresAt: 0,
    hosted: false,
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("runReauthCheck", () => {
  it("refreshes and reauths the live socket when the token is expiring soon", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    let connection = fakeConnection({ accessToken: "old", expiresAt: FIVE_MIN_MS });
    const reauth = vi.fn();
    const refreshAccessToken = vi.fn(() => {
      connection = fakeConnection({ accessToken: "fresh", expiresAt: 2 * FIVE_MIN_MS });
      return Promise.resolve(true);
    });

    await runReauthCheck({
      getConnection: () => connection,
      refreshAccessToken,
      reauth,
    });

    expect(refreshAccessToken).toHaveBeenCalledOnce();
    expect(reauth).toHaveBeenCalledWith("fresh");
  });

  it("does nothing while the token is still fresh", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const reauth = vi.fn();
    const refreshAccessToken = vi.fn(() => Promise.resolve(true));

    await runReauthCheck({
      getConnection: () => fakeConnection({ expiresAt: 60 * 60 * 1000 }),
      refreshAccessToken,
      reauth,
    });

    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(reauth).not.toHaveBeenCalled();
  });

  it("skips reauth when the refresh cannot complete", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const reauth = vi.fn();

    await runReauthCheck({
      getConnection: () => fakeConnection({ expiresAt: FIVE_MIN_MS }),
      refreshAccessToken: () => Promise.resolve(false),
      reauth,
    });

    expect(reauth).not.toHaveBeenCalled();
  });

  it("is a no-op without a connection", async () => {
    const reauth = vi.fn();
    const refreshAccessToken = vi.fn(() => Promise.resolve(true));

    await runReauthCheck({
      getConnection: () => null,
      refreshAccessToken,
      reauth,
    });

    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(reauth).not.toHaveBeenCalled();
  });
});
