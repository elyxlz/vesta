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

// Auth headers first, then the caller's own headers on top so an explicit
// header in `init` wins.
function requestHeaders(init?: RequestInit): Headers {
  const headers = new Headers(authHeaders());
  new Headers(init?.headers).forEach((value, key) => {
    headers.set(key, value);
  });
  return headers;
}

function errorMessage(body: string): string {
  try {
    const parsed: unknown = JSON.parse(body);
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      "error" in parsed &&
      typeof parsed.error === "string"
    ) {
      return parsed.error;
    }
    return body;
  } catch {
    return body;
  }
}

export async function apiFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  await ensureFreshToken();

  let resp = await fetch(apiUrl(path), {
    ...init,
    headers: requestHeaders(init),
  });

  // If 401, force a refresh then retry (the token was rejected even if the
  // local clock thinks it is still valid, e.g. server-side rotation/revocation)
  if (resp.status === 401) {
    const refreshed = await ensureFreshToken(true);
    if (refreshed === "ok") {
      resp = await fetch(apiUrl(path), {
        ...init,
        headers: requestHeaders(init),
      });
    }
  }

  if (!resp.ok) {
    throw new ApiError(resp.status, errorMessage(await resp.text()));
  }
  return resp;
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await apiFetch(path, init);
  return (await resp.json()) as T;
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
