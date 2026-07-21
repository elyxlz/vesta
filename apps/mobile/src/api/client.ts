import { ApiError, createHttpClient } from "@vesta/core";
import type { ConnectionConfig } from "./types";

// The Bearer-auth + refresh-on-401 + retry mechanics live once in @vesta/core; this module
// injects mobile's connection accessors, its 5-min-buffer refresh, and its gateway error
// shaping. `ApiError` is re-exported so endpoints and consumers keep importing it from here.
export { ApiError };

const TOKEN_REFRESH_BUFFER_MS = 5 * 60 * 1000;

export function isTokenExpiringSoon(
  connection: ConnectionConfig,
  now: number = Date.now(),
): boolean {
  return now >= connection.expiresAt - TOKEN_REFRESH_BUFFER_MS;
}

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
  websocketUrl: (path: string, query?: URLSearchParams) => string;
  mediaUrl: (path: string, query?: URLSearchParams) => string;
  getConnection: () => ConnectionConfig | null;
  forceRefresh: () => Promise<boolean>;
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
  let refreshPromise: Promise<ConnectionConfig | null> | null = null;

  const refresh = async (force: boolean): Promise<ConnectionConfig | null> => {
    const current = options.getConnection();
    if (!current) return null;
    if (!force && Date.now() < current.expiresAt - TOKEN_REFRESH_BUFFER_MS) {
      return current;
    }
    if (refreshPromise) return refreshPromise;

    refreshPromise = (async () => {
      if (!current.refreshToken) {
        await options.onSessionExpired();
        return null;
      }
      try {
        const response = await fetch(`${current.url}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: current.refreshToken }),
        });
        if (response.status === 401) {
          await options.onSessionExpired();
          return null;
        }
        if (!response.ok) return current;
        const tokens: {
          access_token: string;
          refresh_token: string;
          expires_in: number;
        } = await response.json();
        const next: ConnectionConfig = {
          ...current,
          accessToken: tokens.access_token,
          refreshToken: tokens.refresh_token,
          expiresAt: Date.now() + tokens.expires_in * 1000,
        };
        await options.onConnectionChange(next);
        return next;
      } catch {
        return current;
      }
    })();

    try {
      return await refreshPromise;
    } finally {
      refreshPromise = null;
    }
  };

  const http = createHttpClient({
    baseUrl: () => options.getConnection()?.url ?? "",
    fetch: (input, init) => fetch(input, init),
    token: () => options.getConnection()?.accessToken ?? null,
    refresh: async () => (await refresh(true)) !== null,
    isExpiring: () => {
      const current = options.getConnection();
      return (
        current !== null &&
        Date.now() >= current.expiresAt - TOKEN_REFRESH_BUFFER_MS
      );
    },
    formatError: apiErrorMessage,
  });

  const request = async (
    path: string,
    init?: RequestInit,
  ): Promise<Response> => {
    if (!options.getConnection())
      throw new Error("Not connected to a Vesta gateway.");
    return http.request(path, init);
  };

  const json = <ResponseBody>(
    path: string,
    init?: RequestInit,
  ): Promise<ResponseBody> => http.json<ResponseBody>(path, init);

  const withToken = (
    path: string,
    query: URLSearchParams,
    protocol: "http" | "ws",
  ): string => {
    const connection = options.getConnection();
    if (!connection) throw new Error("Not connected to a Vesta gateway.");
    query.set("token", connection.accessToken);
    const base =
      protocol === "ws"
        ? connection.url.replace(/^http/, "ws")
        : connection.url;
    return `${base}${path}?${query.toString()}`;
  };

  return {
    request,
    json,
    jsonInit: (method, body) => ({
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
    websocketUrl: (path, query = new URLSearchParams()) =>
      withToken(path, query, "ws"),
    mediaUrl: (path, query = new URLSearchParams()) =>
      withToken(path, query, "http"),
    getConnection: options.getConnection,
    forceRefresh: async () => (await refresh(true)) !== null,
  };
}
