import {
  createHttpClient,
  jsonInit,
  type FetchLike,
  type HttpClient,
  type HttpDeps,
} from "../transport/http";

// The gateway session every client holds: the connection it minted, the refresh that keeps its
// access token live, and the two carriers of that token (the Bearer header the http client stamps,
// the `?token=` query a socket handshake or media element needs). Apps inject only persistence.
export interface ConnectionConfig {
  url: string;
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  // A hosted (vesta.run) connection was minted by the apex, not by a connect key. One with no
  // refresh token re-authorizes through the app instead of POST /auth/refresh.
  hosted?: boolean;
}

// A token this close to expiry is refreshed before it is used, so a client waking from sleep never
// presents one that died while it was away.
export const TOKEN_REFRESH_BUFFER_MS = 5 * 60 * 1000;
// How often a live controller re-checks the token and rotates it in-band over the sync socket.
export const REAUTH_POLL_MS = 60_000;
// A gateway that does not answer /health or /auth/session within this is unreachable.
export const GATEWAY_CONNECT_TIMEOUT_MS = 8_000;

export function isTokenExpiringSoon(
  connection: ConnectionConfig | null,
  now: number = Date.now(),
): boolean {
  return (
    connection !== null && now >= connection.expiresAt - TOKEN_REFRESH_BUFFER_MS
  );
}

// "ok": the token is fresh, or was just refreshed. "transient": the refresh could not complete
// (network, a server error, a hosted re-authorization in flight); retrying later may succeed.
// "expired": the gateway definitively rejected the refresh token; only a new sign-in recovers.
export type RefreshResult = "ok" | "transient" | "expired";

export type RefreshOutcome =
  | { kind: "ok"; connection: ConnectionConfig }
  | { kind: "transient" }
  | { kind: "expired" };

interface TokenGrant {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

function tokenGrant(data: unknown): TokenGrant | null {
  if (data === null || typeof data !== "object") return null;
  if (!("access_token" in data) || !("refresh_token" in data)) return null;
  const { access_token, refresh_token } = data;
  if (typeof access_token !== "string" || typeof refresh_token !== "string")
    return null;
  const expires_in = "expires_in" in data ? data.expires_in : undefined;
  return {
    access_token,
    refresh_token,
    // The exchange omits it on some gateways; an hour is the gateway's own default.
    expires_in: typeof expires_in === "number" ? expires_in : 3600,
  };
}

function granted(
  url: string,
  grant: TokenGrant,
  now: number,
  hosted: boolean | undefined,
): ConnectionConfig {
  const connection: ConnectionConfig = {
    url,
    accessToken: grant.access_token,
    refreshToken: grant.refresh_token,
    expiresAt: now + grant.expires_in * 1000,
  };
  if (hosted !== undefined) connection.hosted = hosted;
  return connection;
}

// POST /auth/refresh, the one owner of its wire shape. A network failure is transient, never a
// success with the stale connection, so an http retry never re-presents the token that just failed.
export async function refreshConnection(
  fetch: FetchLike,
  connection: ConnectionConfig,
  now: number = Date.now(),
): Promise<RefreshOutcome> {
  try {
    const response = await fetch(
      `${connection.url}/auth/refresh`,
      jsonInit("POST", { refresh_token: connection.refreshToken }),
    );
    if (response.status === 401) return { kind: "expired" };
    if (!response.ok) return { kind: "transient" };
    const grant = tokenGrant(await response.json());
    if (grant === null) return { kind: "transient" };
    return {
      kind: "ok",
      connection: granted(connection.url, grant, now, connection.hosted),
    };
  } catch {
    return { kind: "transient" };
  }
}

export type ConnectFailure =
  "unreachable" | "invalid_key" | "session_refused" | "malformed";

const CONNECT_MESSAGES: Record<ConnectFailure, string> = {
  unreachable: "could not reach the gateway",
  invalid_key: "invalid connection key",
  session_refused: "could not create a gateway session",
  malformed: "session response missing tokens",
};

export class ConnectError extends Error {
  readonly reason: ConnectFailure;

  constructor(reason: ConnectFailure) {
    super(CONNECT_MESSAGES[reason]);
    this.name = "ConnectError";
    this.reason = reason;
  }
}

async function fetchWithinBudget(
  fetch: FetchLike,
  url: string,
  init?: RequestInit,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort();
  }, GATEWAY_CONNECT_TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch {
    throw new ConnectError("unreachable");
  } finally {
    clearTimeout(timer);
  }
}

export function normalizeGatewayUrl(url: string): string {
  let normalized = url.trim();
  while (normalized.endsWith("/")) normalized = normalized.slice(0, -1);
  return normalized;
}

// GET /health then POST /auth/session: exchange a connect key for a session. The one owner of the
// connect wire shape; an app maps ConnectError.reason to its own copy when it wants to.
export async function mintConnection(
  fetch: FetchLike,
  url: string,
  apiKey: string,
  now: number = Date.now(),
): Promise<ConnectionConfig> {
  const normalized = normalizeGatewayUrl(url);
  const health = await fetchWithinBudget(fetch, `${normalized}/health`);
  if (!health.ok) throw new ConnectError("unreachable");
  const response = await fetchWithinBudget(
    fetch,
    `${normalized}/auth/session`,
    jsonInit("POST", { api_key: apiKey }),
  );
  if (response.status === 401) throw new ConnectError("invalid_key");
  if (!response.ok) throw new ConnectError("session_refused");
  const grant = tokenGrant(await response.json());
  if (grant === null) throw new ConnectError("malformed");
  return granted(normalized, grant, now, false);
}

export interface SessionDeps {
  fetch: FetchLike;
  // The app's persistence. `read` answers synchronously from what the app loaded; `write` persists
  // a rotation before the session reports it, so a token the app stored is always the live one.
  read: () => ConnectionConfig | null;
  write: (next: ConnectionConfig) => Promise<void> | void;
  // Fires when a refresh is definitively rejected, so the app can sign the user out.
  onExpired?: () => void;
  // Re-authorizes a connection that has no refresh token (a hosted web session: the apex cookie is
  // the refresh root, so the app bounces through its authorize flow). Absent, such an expiry is
  // final.
  reauthorize?: () => void;
  formatError?: HttpDeps["formatError"];
  now?: () => number;
}

export interface Session {
  getConnection: () => ConnectionConfig | null;
  isExpiring: () => boolean;
  // Refreshes an expiring token (or any token when forced); concurrent calls share one refresh.
  ensureFresh: (force?: boolean) => Promise<RefreshResult>;
  // The one place the access token is stamped into a URL: a socket handshake and a media element
  // send no headers. Refreshing first is what makes it impossible to dial with an expired token.
  authedUrl: (path: string, query?: URLSearchParams) => Promise<string>;
  websocketUrl: (path: string, query?: URLSearchParams) => Promise<string>;
  // The app's one http client: Bearer-stamped, pre-flighted, retried once on a 401.
  http: HttpClient;
}

export const NOT_CONNECTED = "not connected to a gateway";

export function createSession(deps: SessionDeps): Session {
  const now = deps.now ?? Date.now;
  let inFlight: Promise<RefreshResult> | null = null;

  const refresh = async (): Promise<RefreshResult> => {
    const connection = deps.read();
    if (connection === null) return "transient";
    if (!connection.refreshToken) {
      if (deps.reauthorize) {
        deps.reauthorize();
        return "transient";
      }
      deps.onExpired?.();
      return "expired";
    }
    const outcome = await refreshConnection(deps.fetch, connection, now());
    if (outcome.kind === "ok") {
      // A rotation the app cannot persist is not a fresh token: the next call refreshes again.
      try {
        await deps.write(outcome.connection);
      } catch {
        return "transient";
      }
      return "ok";
    }
    if (outcome.kind === "expired") deps.onExpired?.();
    return outcome.kind;
  };

  const ensureFresh = async (force = false): Promise<RefreshResult> => {
    if (!force && !isTokenExpiringSoon(deps.read(), now())) return "ok";
    if (inFlight) return inFlight;
    inFlight = refresh();
    try {
      return await inFlight;
    } finally {
      inFlight = null;
    }
  };

  const authedUrl = async (
    path: string,
    query = new URLSearchParams(),
  ): Promise<string> => {
    await ensureFresh();
    const connection = deps.read();
    if (connection === null) throw new Error(NOT_CONNECTED);
    query.set("token", connection.accessToken);
    return `${connection.url}${path}?${query.toString()}`;
  };

  const http = createHttpClient({
    baseUrl: () => {
      const connection = deps.read();
      if (connection === null) throw new Error(NOT_CONNECTED);
      return connection.url;
    },
    fetch: deps.fetch,
    token: () => deps.read()?.accessToken ?? null,
    refresh: async () => (await ensureFresh(true)) === "ok",
    isExpiring: () => isTokenExpiringSoon(deps.read(), now()),
    formatError: deps.formatError,
  });

  return {
    getConnection: deps.read,
    isExpiring: () => isTokenExpiringSoon(deps.read(), now()),
    ensureFresh,
    authedUrl,
    websocketUrl: async (path, query) =>
      (await authedUrl(path, query)).replace(/^http/, "ws"),
    http,
  };
}

// One reauth tick over a live socket: when the token is close to expiring, refresh it and hand the
// fresh token to the socket in-band. A no-op while the token is fresh or when the refresh cannot
// complete, so the socket is never torn down to rotate a token.
export async function runReauthCheck(
  session: Session,
  reauth: (token: string) => void,
): Promise<void> {
  if (!session.isExpiring()) return;
  if ((await session.ensureFresh()) !== "ok") return;
  const connection = session.getConnection();
  if (connection) reauth(connection.accessToken);
}
