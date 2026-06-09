import { getConnection, updateTokens, isTokenExpiringSoon } from "./connection";
import { startHostedLogin } from "./pkce";

let refreshPromise: Promise<boolean> | null = null;

export async function ensureFreshToken(force = false): Promise<boolean> {
  if (!force && !isTokenExpiringSoon()) return true;

  // Deduplicate concurrent refresh calls
  if (refreshPromise) return refreshPromise;

  refreshPromise = doRefresh();
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

async function doRefresh(): Promise<boolean> {
  const conn = getConnection();
  if (!conn) return false;

  // Hosted (vesta.run) connections have no refresh token: re-run the PKCE
  // authorize flow. With the apex session cookie still valid this is a silent
  // full-page bounce that returns a fresh token; otherwise it lands on sign-in.
  if (conn.hosted) {
    void startHostedLogin();
    return false;
  }

  try {
    const resp = await fetch(`${conn.url}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: conn.refreshToken }),
    });
    if (!resp.ok) return false;
    const data = await resp.json();
    updateTokens(data.access_token, data.refresh_token, data.expires_in);
    return true;
  } catch {
    return false;
  }
}
