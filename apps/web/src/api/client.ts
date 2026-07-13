import { apiUrl, authHeaders } from "@/lib/connection";
import { ensureFreshToken } from "@/lib/token-refresh";

/// A non-2xx API response: the server's error message plus the HTTP status,
/// so callers can react to specific statuses (409 conflict, 4xx rejection).
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  await ensureFreshToken();

  let resp = await fetch(apiUrl(path), {
    ...init,
    headers: { ...authHeaders(), ...init?.headers },
  });

  // If 401, force a refresh then retry (the token was rejected even if the
  // local clock thinks it is still valid, e.g. server-side rotation/revocation)
  if (resp.status === 401) {
    const refreshed = await ensureFreshToken(true);
    if (refreshed === "ok") {
      resp = await fetch(apiUrl(path), {
        ...init,
        headers: { ...authHeaders(), ...init?.headers },
      });
    }
  }

  if (!resp.ok) {
    const body = await resp.text();
    let msg: string;
    try {
      msg = JSON.parse(body).error ?? body;
    } catch {
      msg = body;
    }
    throw new ApiError(resp.status, msg);
  }
  return resp;
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await apiFetch(path, init);
  return resp.json();
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
