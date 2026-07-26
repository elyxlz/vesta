import { afterEach, describe, expect, it, vi } from "vitest";
import {
  connectWithKey,
  resumeGatewaySession,
  signInWithVestaAccount,
} from "./auth";

const { openAuthSessionAsync } = vi.hoisted(() => ({
  openAuthSessionAsync: vi.fn(),
}));

vi.mock("expo-crypto", () => ({
  randomUUID: () => "00000000-0000-4000-8000-000000000000",
  digestStringAsync: () => Promise.resolve("challenge=="),
  CryptoDigestAlgorithm: { SHA256: "SHA256" },
  CryptoEncoding: { BASE64: "base64" },
}));
vi.mock("expo-web-browser", () => ({ openAuthSessionAsync }));

describe("gateway connection", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("uses a private browser session for account sign-in", async () => {
    vi.stubGlobal("__DEV__", true);
    openAuthSessionAsync.mockResolvedValue({ type: "cancel" });

    await expect(signInWithVestaAccount()).resolves.toBeNull();

    expect(openAuthSessionAsync).toHaveBeenCalledWith(
      expect.stringContaining("https://vesta.run/api/authorize?"),
      "vesta://oauth/callback",
      { preferEphemeralSession: true },
    );
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
