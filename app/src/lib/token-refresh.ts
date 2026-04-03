import { getConnection, updateTokens, isTokenExpiringSoon } from "./connection";

let refreshPromise: Promise<boolean> | null = null;

export async function ensureFreshToken(): Promise<boolean> {
  if (!isTokenExpiringSoon()) return true;

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
