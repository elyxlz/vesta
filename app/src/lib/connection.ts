const STORAGE_KEY = "vesta-connection";

export interface ConnectionConfig {
  url: string;
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}

export function getConnection(): ConnectionConfig | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    // Migration: clear legacy format that stored apiKey
    if (parsed.apiKey && !parsed.accessToken) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    if (parsed.url && parsed.accessToken && parsed.refreshToken) return parsed;
    return null;
  } catch {
    return null;
  }
}

export function setConnection(
  url: string,
  accessToken: string,
  refreshToken: string,
  expiresIn: number,
): void {
  const normalized = url.replace(/\/+$/, "");
  const expiresAt = Date.now() + expiresIn * 1000;
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ url: normalized, accessToken, refreshToken, expiresAt }),
  );
}

export function updateTokens(
  accessToken: string,
  refreshToken: string,
  expiresIn: number,
): void {
  const conn = getConnection();
  if (!conn) return;
  setConnection(conn.url, accessToken, refreshToken, expiresIn);
}

export function clearConnection(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function isConnected(): boolean {
  return getConnection() !== null;
}

export function isTokenExpiringSoon(): boolean {
  const conn = getConnection();
  if (!conn) return false;
  return Date.now() > conn.expiresAt - 5 * 60 * 1000; // 5 min buffer
}

export function authHeaders(): Record<string, string> {
  const conn = getConnection();
  if (!conn) return {};
  return { Authorization: `Bearer ${conn.accessToken}` };
}

export function apiUrl(path: string): string {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  return `${conn.url}${path}`;
}

export function wsUrl(name: string): string {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  const base = conn.url.replace(/^http/, "ws");
  return `${base}/agents/${name}/ws?token=${encodeURIComponent(conn.accessToken)}`;
}
