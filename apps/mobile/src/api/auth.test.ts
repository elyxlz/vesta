import { afterEach, describe, expect, it, vi } from "vitest";
import { connectWithKey, resumeGatewaySession } from "./auth";

vi.mock("expo-crypto", () => ({}));
vi.mock("expo-web-browser", () => ({}));

describe("gateway connection", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("stops waiting when an unreachable gateway never responds", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      ),
    );

    const connection = connectWithKey("https://offline.vesta.run", "key");
    const result = expect(connection).rejects.toThrow(
      "Could not reach this Vesta gateway.",
    );
    await vi.runAllTimersAsync();
    await result;
  });

  it("refreshes a saved gateway session before reconnecting", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            access_token: "new-access",
            refresh_token: "new-refresh",
            expires_in: 7200,
          }),
          { status: 200 },
        ),
      ),
    );

    const connection = await resumeGatewaySession({
      url: "https://gateway.vesta.run",
      accessToken: "old-access",
      refreshToken: "old-refresh",
      expiresAt: 0,
      hosted: true,
    });

    expect(connection).toMatchObject({
      accessToken: "new-access",
      refreshToken: "new-refresh",
      hosted: true,
    });
    expect(fetch).toHaveBeenCalledWith(
      "https://gateway.vesta.run/auth/refresh",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("rejects an expired saved gateway session", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 401 })),
    );

    await expect(
      resumeGatewaySession({
        url: "https://gateway.vesta.run",
        accessToken: "old-access",
        refreshToken: "expired-refresh",
        expiresAt: 0,
        hosted: false,
      }),
    ).rejects.toThrow(
      "This saved gateway session has expired. Connect to it again.",
    );
  });
});
