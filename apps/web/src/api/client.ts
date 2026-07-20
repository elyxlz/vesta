import { ApiError, createHttpClient } from "@vesta/core";
import { getConnection, isTokenExpiringSoon } from "@/lib/connection";
import { ensureFreshToken } from "@/lib/token-refresh";

// The Bearer-auth + refresh-on-401 + error-shaping mechanics live once in @vesta/core; web
// injects its own connection accessors and refresh implementation. `ApiError` is re-exported
// so the ~10 api/* modules and create-flow keep importing it from here.
export { ApiError };

const client = createHttpClient({
  baseUrl: () => {
    const conn = getConnection();
    if (!conn) throw new Error("not connected to vestad");
    return conn.url;
  },
  fetch: (input, init) => fetch(input, init),
  token: () => getConnection()?.accessToken ?? null,
  refresh: async () => (await ensureFreshToken(true)) === "ok",
  isExpiring: () => isTokenExpiringSoon(),
});

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return client.request(path, init);
}

export function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  return client.json<T>(path, init);
}

// The one place that owns the JSON request shape (method + Content-Type + serialized body),
// so individual endpoints don't each re-spell the same header and JSON.stringify.
export function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}
