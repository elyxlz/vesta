import { describe, expect, it, vi } from "vitest";
import {
  ConnectError,
  TOKEN_REFRESH_BUFFER_MS,
  createSession,
  isTokenExpiringSoon,
  mintConnection,
  refreshConnection,
  runReauthCheck,
  type ConnectionConfig,
  type FetchLike,
} from "..";

const NOW = 1_800_000_000_000;

function connection(
  overrides: Partial<ConnectionConfig> = {},
): ConnectionConfig {
  return {
    url: "https://gateway.test",
    accessToken: "access",
    refreshToken: "refresh",
    expiresAt: NOW + 60 * 60 * 1000,
    ...overrides,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const GRANT = {
  access_token: "next",
  refresh_token: "next-refresh",
  expires_in: 3600,
};

interface Harness {
  fetch: ReturnType<typeof vi.fn<FetchLike>>;
  stored: ConnectionConfig | null;
  writes: ConnectionConfig[];
  expired: number;
  reauthorized: number;
}

function harness(
  initial: ConnectionConfig | null,
  options: {
    reauthorize?: boolean;
    write?: (next: ConnectionConfig) => Promise<void>;
  } = {},
) {
  const state: Harness = {
    fetch: vi.fn<FetchLike>(),
    stored: initial,
    writes: [],
    expired: 0,
    reauthorized: 0,
  };
  const session = createSession({
    fetch: state.fetch,
    read: () => state.stored,
    write: async (next) => {
      if (options.write) await options.write(next);
      state.stored = next;
      state.writes.push(next);
    },
    onExpired: () => {
      state.expired += 1;
    },
    reauthorize: options.reauthorize
      ? () => {
          state.reauthorized += 1;
        }
      : undefined,
    now: () => NOW,
  });
  return { session, state };
}

describe("isTokenExpiringSoon", () => {
  it("is false with no connection and true inside the refresh buffer", () => {
    expect(isTokenExpiringSoon(null, NOW)).toBe(false);
    expect(isTokenExpiringSoon(connection(), NOW)).toBe(false);
    expect(
      isTokenExpiringSoon(
        connection({ expiresAt: NOW + TOKEN_REFRESH_BUFFER_MS }),
        NOW,
      ),
    ).toBe(true);
  });
});

describe("refreshConnection", () => {
  it("returns the rotated connection on a grant, keeping the gateway and hosted flag", async () => {
    const fetch = vi.fn<FetchLike>().mockResolvedValue(json(GRANT));
    const outcome = await refreshConnection(
      fetch,
      connection({ hosted: true }),
      NOW,
    );
    expect(outcome).toEqual({
      kind: "ok",
      connection: {
        url: "https://gateway.test",
        accessToken: "next",
        refreshToken: "next-refresh",
        expiresAt: NOW + 3600 * 1000,
        hosted: true,
      },
    });
    expect(fetch).toHaveBeenCalledWith(
      "https://gateway.test/auth/refresh",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ refresh_token: "refresh" }),
      }),
    );
  });

  it("is expired on a 401, transient on any other failure or a malformed grant", async () => {
    const cases: [Response | Error, string][] = [
      [json({ error: "revoked" }, 401), "expired"],
      [json({ error: "down" }, 503), "transient"],
      [json({ access_token: "only" }), "transient"],
      [new TypeError("network down"), "transient"],
    ];
    for (const [answer, kind] of cases) {
      const fetch = vi.fn<FetchLike>();
      if (answer instanceof Error) fetch.mockRejectedValue(answer);
      else fetch.mockResolvedValue(answer);
      expect((await refreshConnection(fetch, connection(), NOW)).kind).toBe(
        kind,
      );
    }
  });
});

describe("createSession", () => {
  it("answers ok without a request while the token is fresh", async () => {
    const { session, state } = harness(connection());
    expect(await session.ensureFresh()).toBe("ok");
    expect(state.fetch).not.toHaveBeenCalled();
  });

  it("refreshes an expiring token once, persisting the rotation before reporting ok", async () => {
    const { session, state } = harness(
      connection({ expiresAt: NOW + TOKEN_REFRESH_BUFFER_MS - 1 }),
    );
    state.fetch.mockResolvedValue(json(GRANT));
    const [first, second] = await Promise.all([
      session.ensureFresh(),
      session.ensureFresh(),
    ]);
    expect([first, second]).toEqual(["ok", "ok"]);
    expect(state.fetch).toHaveBeenCalledTimes(1);
    expect(state.writes.map((c) => c.accessToken)).toEqual(["next"]);
    expect(session.getConnection()?.accessToken).toBe("next");
  });

  it("reports a network failure as transient, never as a fresh token", async () => {
    const { session, state } = harness(connection({ expiresAt: NOW }));
    state.fetch.mockRejectedValue(new TypeError("offline"));
    expect(await session.ensureFresh()).toBe("transient");
    expect(state.writes).toEqual([]);
    expect(session.getConnection()?.accessToken).toBe("access");
  });

  it("reports a rotation the app cannot persist as transient", async () => {
    const { session, state } = harness(connection({ expiresAt: NOW }), {
      write: () => Promise.reject(new Error("keychain locked")),
    });
    state.fetch.mockResolvedValue(json(GRANT));
    expect(await session.ensureFresh()).toBe("transient");
  });

  it("signals expiry once when the gateway rejects the refresh token", async () => {
    const { session, state } = harness(connection({ expiresAt: NOW }));
    state.fetch.mockResolvedValue(json({ error: "revoked" }, 401));
    expect(await session.ensureFresh()).toBe("expired");
    expect(state.expired).toBe(1);
  });

  it("re-authorizes a connection with no refresh token when the app can, else expires it", async () => {
    const hosted = harness(connection({ refreshToken: "", expiresAt: NOW }), {
      reauthorize: true,
    });
    expect(await hosted.session.ensureFresh()).toBe("transient");
    expect(hosted.state.reauthorized).toBe(1);
    expect(hosted.state.fetch).not.toHaveBeenCalled();

    const bare = harness(connection({ refreshToken: "", expiresAt: NOW }));
    expect(await bare.session.ensureFresh()).toBe("expired");
    expect(bare.state.expired).toBe(1);
  });

  it("stamps the token into an authed URL after refreshing an expiring one", async () => {
    const { session, state } = harness(connection({ expiresAt: NOW }));
    state.fetch.mockResolvedValue(json(GRANT));
    expect(await session.websocketUrl("/sync")).toBe(
      "wss://gateway.test/sync?token=next",
    );
    expect(await session.authedUrl("/a", new URLSearchParams({ x: "1" }))).toBe(
      "https://gateway.test/a?x=1&token=next",
    );
  });

  it("refuses an authed URL and an http call with no connection", async () => {
    const { session } = harness(null);
    await expect(session.authedUrl("/a")).rejects.toThrow(
      "not connected to a gateway",
    );
    await expect(session.http.request("/agents")).rejects.toThrow(
      "not connected to a gateway",
    );
  });

  it("pre-flights an expiring token before the http client sends", async () => {
    const { session, state } = harness(connection({ expiresAt: NOW }));
    state.fetch
      .mockResolvedValueOnce(json(GRANT))
      .mockResolvedValueOnce(json({ ok: true }));
    await session.http.json("/agents");
    const [refresh, request] = state.fetch.mock.calls;
    expect(refresh?.[0]).toBe("https://gateway.test/auth/refresh");
    expect(request?.[0]).toBe("https://gateway.test/agents");
    expect(new Headers(request?.[1]?.headers).get("Authorization")).toBe(
      "Bearer next",
    );
  });

  it("retries once on a 401 with the refreshed token and never with the stale one", async () => {
    const { session, state } = harness(connection());
    state.fetch
      .mockResolvedValueOnce(json({ error: "expired" }, 401))
      .mockResolvedValueOnce(json(GRANT))
      .mockResolvedValueOnce(json({ ok: true }));
    await session.http.json("/agents");
    expect(state.fetch).toHaveBeenCalledTimes(3);
    const retry = state.fetch.mock.calls[2];
    expect(new Headers(retry?.[1]?.headers).get("Authorization")).toBe(
      "Bearer next",
    );

    const offline = harness(connection());
    offline.state.fetch
      .mockResolvedValueOnce(json({ error: "expired" }, 401))
      .mockRejectedValueOnce(new TypeError("offline"));
    await expect(offline.session.http.json("/agents")).rejects.toThrow();
    expect(offline.state.fetch).toHaveBeenCalledTimes(2);
  });
});

describe("runReauthCheck", () => {
  it("hands the socket a fresh token only after an expiring one was refreshed", async () => {
    const reauth = vi.fn<(token: string) => void>();
    const fresh = harness(connection());
    await runReauthCheck(fresh.session, reauth);
    expect(reauth).not.toHaveBeenCalled();

    const expiring = harness(connection({ expiresAt: NOW }));
    expiring.state.fetch.mockResolvedValue(json(GRANT));
    await runReauthCheck(expiring.session, reauth);
    expect(reauth).toHaveBeenCalledWith("next");

    const failing = harness(connection({ expiresAt: NOW }));
    failing.state.fetch.mockRejectedValue(new TypeError("offline"));
    await runReauthCheck(failing.session, reauth);
    expect(reauth).toHaveBeenCalledTimes(1);
  });
});

describe("mintConnection", () => {
  it("checks reachability, exchanges the key, and normalizes the gateway url", async () => {
    const fetch = vi
      .fn<FetchLike>()
      .mockResolvedValueOnce(new Response("ok"))
      .mockResolvedValueOnce(json(GRANT));
    const minted = await mintConnection(
      fetch,
      " https://gateway.test/ ",
      "key",
      NOW,
    );
    expect(minted).toEqual({
      url: "https://gateway.test",
      accessToken: "next",
      refreshToken: "next-refresh",
      expiresAt: NOW + 3600 * 1000,
      hosted: false,
    });
    expect(fetch.mock.calls[0]?.[0]).toBe("https://gateway.test/health");
    expect(fetch.mock.calls[1]?.[1]?.body).toBe(
      JSON.stringify({ api_key: "key" }),
    );
  });

  it("names the failure: unreachable, invalid key, refused, malformed", async () => {
    const unreachable = vi
      .fn<FetchLike>()
      .mockRejectedValue(new TypeError("down"));
    await expect(
      mintConnection(unreachable, "https://g", "k"),
    ).rejects.toMatchObject({
      reason: "unreachable",
    });
    const invalid = vi
      .fn<FetchLike>()
      .mockResolvedValueOnce(new Response("ok"))
      .mockResolvedValueOnce(json({ error: "nope" }, 401));
    await expect(
      mintConnection(invalid, "https://g", "k"),
    ).rejects.toMatchObject({
      reason: "invalid_key",
    });
    const refused = vi
      .fn<FetchLike>()
      .mockResolvedValueOnce(new Response("ok"))
      .mockResolvedValueOnce(json({ error: "nope" }, 500));
    await expect(
      mintConnection(refused, "https://g", "k"),
    ).rejects.toMatchObject({
      reason: "session_refused",
    });
    const malformed = vi
      .fn<FetchLike>()
      .mockResolvedValueOnce(new Response("ok"))
      .mockResolvedValueOnce(json({ access_token: "only" }));
    const thrown: unknown = await mintConnection(
      malformed,
      "https://g",
      "k",
    ).catch((error: unknown) => error);
    expect(thrown).toBeInstanceOf(ConnectError);
    expect(thrown).toMatchObject({ reason: "malformed" });
  });
});
