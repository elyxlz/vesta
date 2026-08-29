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
  // With the token expiring soon, the reauth carries the freshly refreshed token, and only when the
  // refresh actually succeeds: a transient failure or a definitively expired session sends nothing.
  it.each<{ name: string; result: RefreshResult; reauthedWith: string | null }>(
    [
      {
        name: "the fresh token when the refresh succeeds",
        result: "ok",
        reauthedWith: "fresh",
      },
      {
        name: "nothing when the refresh is transiently unavailable",
        result: "transient",
        reauthedWith: null,
      },
      {
        name: "nothing when the session is definitively expired",
        result: "expired",
        reauthedWith: null,
      },
    ],
  )("reauths $name", async ({ result, reauthedWith }) => {
    mocks.expiring = true;
    mocks.connection = fakeConnection("old");
    mocks.ensureFreshToken.mockImplementation(() => {
      if (result === "ok") mocks.connection = fakeConnection("fresh");
      return Promise.resolve(result);
    });
    const reauth = vi.fn();

    await runReauthCheck(reauth);

    expect(mocks.ensureFreshToken).toHaveBeenCalledOnce();
    if (reauthedWith === null) expect(reauth).not.toHaveBeenCalled();
    else expect(reauth).toHaveBeenCalledWith(reauthedWith);
  });

  it("does not attempt a refresh while the token is still fresh", async () => {
    mocks.expiring = false;
    mocks.connection = fakeConnection("tok");
    const reauth = vi.fn();

    await runReauthCheck(reauth);

    expect(mocks.ensureFreshToken).not.toHaveBeenCalled();
    expect(reauth).not.toHaveBeenCalled();
  });
});
