import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConnectionConfig } from "@/lib/connection";
import type { RefreshResult } from "@/lib/token-refresh";
import { runReauthCheck } from "./reauth-poll";

const mocks = vi.hoisted(() => ({
  connection: null as ConnectionConfig | null,
  expiring: false,
  ensureFreshToken: vi.fn<() => Promise<RefreshResult>>(),
}));

vi.mock("@/lib/connection", () => ({
  getConnection: () => mocks.connection,
  isTokenExpiringSoon: () => mocks.expiring,
}));

vi.mock("@/lib/token-refresh", () => ({
  ensureFreshToken: mocks.ensureFreshToken,
}));

function fakeConnection(accessToken: string): ConnectionConfig {
  return {
    url: "https://gateway.test",
    accessToken,
    refreshToken: "refresh",
    expiresAt: 0,
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("runReauthCheck", () => {
  it("refreshes and reauths the live socket when the token is expiring soon", async () => {
    mocks.expiring = true;
    mocks.connection = fakeConnection("old");
    mocks.ensureFreshToken.mockImplementation(() => {
      mocks.connection = fakeConnection("fresh");
      return Promise.resolve("ok");
    });
    const reauth = vi.fn();

    await runReauthCheck(reauth);

    expect(mocks.ensureFreshToken).toHaveBeenCalledOnce();
    expect(reauth).toHaveBeenCalledWith("fresh");
  });

  it("does nothing while the token is still fresh", async () => {
    mocks.expiring = false;
    mocks.connection = fakeConnection("tok");
    const reauth = vi.fn();

    await runReauthCheck(reauth);

    expect(mocks.ensureFreshToken).not.toHaveBeenCalled();
    expect(reauth).not.toHaveBeenCalled();
  });

  it("skips reauth when the refresh cannot complete", async () => {
    mocks.expiring = true;
    mocks.connection = fakeConnection("old");
    mocks.ensureFreshToken.mockResolvedValue("transient");
    const reauth = vi.fn();

    await runReauthCheck(reauth);

    expect(reauth).not.toHaveBeenCalled();
  });

  it("skips reauth when the session is definitively expired", async () => {
    mocks.expiring = true;
    mocks.connection = fakeConnection("old");
    mocks.ensureFreshToken.mockResolvedValue("expired");
    const reauth = vi.fn();

    await runReauthCheck(reauth);

    expect(reauth).not.toHaveBeenCalled();
  });
});
