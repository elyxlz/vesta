import { getConnection, updateTokens, isTokenExpiringSoon } from "./connection";
import { startHostedLogin } from "./pkce";

/**
 * "ok"       — token is fresh (or was just refreshed).
 * "transient"— refresh couldn't complete (network/server error, or a hosted
 *              re-auth bounce is in flight); retrying later may succeed.
 * "expired"  — vestad definitively rejected the refresh token (expired,
 *              revoked, or reused): the session is dead and only a full
 *              re-auth can recover. Callers must stop retrying.
 */
export type RefreshResult = "ok" | "transient" | "expired";

let refreshPromise: Promise<RefreshResult> | null = null;

export async function ensureFreshToken(force = false): Promise<RefreshResult> {
  if (!force && !isTokenExpiringSoon()) return "ok";

  // Deduplicate concurrent refresh calls
  if (refreshPromise) return refreshPromise;

  refreshPromise = doRefresh();
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

async function doRefresh(): Promise<RefreshResult> {
  const conn = getConnection();
  if (!conn) return "transient";

  // Hosted (vesta.run) connections have no refresh token: re-run the PKCE
  // authorize flow. With the apex session cookie still valid this is a silent
  // full-page bounce that returns a fresh token; otherwise it lands on sign-in.
  // Either way the navigation takes over — report transient, not expired.
  if (conn.hosted) {
    void startHostedLogin();
    return "transient";
  }

  try {
    const resp = await fetch(`${conn.url}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: conn.refreshToken }),
    });
    if (resp.status === 401) return "expired";
    if (!resp.ok) return "transient";
    const data = await resp.json();
    updateTokens(data.access_token, data.refresh_token, data.expires_in);
    return "ok";
  } catch {
    return "transient";
  }
}
