import {
  ApiError,
  createServiceKeyCache,
  createSession,
  jsonInit,
  type ConnectionConfig,
  type Session,
  type ServiceKeyCache,
} from "@vesta/core";

// The mobile gateway session: @vesta/core owns the refresh, the expiry buffer, the token-in-URL
// carriers, and the one http client; this adapter injects SecureStore-backed persistence, the
// sign-out on a rejected refresh, and the gateway error shaping (an HTML body from a proxy is never
// shown). `ApiError` is re-exported so consumers keep importing it from here.
export { ApiError };

interface ClientOptions {
  getConnection: () => ConnectionConfig | null;
  onConnectionChange: (connection: ConnectionConfig) => Promise<void>;
  onSessionExpired: () => Promise<void>;
}

export interface ApiClient {
  request: (path: string, init?: RequestInit) => Promise<Response>;
  json: <ResponseBody>(
    path: string,
    init?: RequestInit,
  ) => Promise<ResponseBody>;
  jsonInit: (method: string, body: unknown) => RequestInit;
  authedUrl: (path: string, query?: URLSearchParams) => Promise<string>;
  websocketUrl: (path: string, query?: URLSearchParams) => Promise<string>;
  getConnection: () => ConnectionConfig | null;
  forceRefresh: () => Promise<boolean>;
  // The core session this client fronts: the controller dials and refreshes through it.
  session: Session;
  // The client's own service keys, so a client built by a test never shares them and
  // reconnecting to another gateway keeps the client while missing the cache.
  serviceKeys: ServiceKeyCache;
}

function apiErrorMessage(response: Response, body: string): string {
  const statusText = response.statusText.trim();
  const fallback = statusText
    ? `Gateway request failed (${response.status} ${statusText}).`
    : `Gateway request failed with status ${response.status}.`;
  if (!body) return fallback;

  try {
    const parsed: { error?: unknown } = JSON.parse(body);
    if (typeof parsed.error === "string" && parsed.error.trim()) {
      return parsed.error;
    }
  } catch {
    // Non-JSON errors are handled below.
  }

  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  const looksLikeHtml =
    contentType.includes("text/html") ||
    /^\s*<!doctype\s+html/i.test(body) ||
    /^\s*<html(?:\s|>)/i.test(body);
  return looksLikeHtml ? fallback : body;
}

export function createApiClient(options: ClientOptions): ApiClient {
  const session = createSession({
    fetch: (input, init) => fetch(input, init),
    read: options.getConnection,
    write: options.onConnectionChange,
    onExpired: () => {
      void options.onSessionExpired();
    },
    formatError: apiErrorMessage,
  });
  const forceRefresh = async (): Promise<boolean> =>
    (await session.ensureFresh(true)) === "ok";

  return {
    request: session.http.request,
    json: session.http.json,
    jsonInit,
    authedUrl: session.authedUrl,
    websocketUrl: session.websocketUrl,
    getConnection: options.getConnection,
    forceRefresh,
    session,
    serviceKeys: createServiceKeyCache({
      http: session.http,
      gateway: () => options.getConnection()?.url ?? null,
    }),
  };
}
