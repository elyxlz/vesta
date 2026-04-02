const STORAGE_KEY = "vesta-connection";

export interface ConnectionConfig {
  url: string;
  apiKey: string;
}

export function getConnection(): ConnectionConfig | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ConnectionConfig;
    if (parsed.url && parsed.apiKey) return parsed;
    return null;
  } catch {
    return null;
  }
}

export function setConnection(url: string, apiKey: string): void {
  const normalized = url.replace(/\/+$/, "");
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ url: normalized, apiKey }));
}

export function clearConnection(): void {
  localStorage.removeItem(STORAGE_KEY);
}

export function isConnected(): boolean {
  return getConnection() !== null;
}

export function authHeaders(): Record<string, string> {
  const conn = getConnection();
  if (!conn) return {};
  return { Authorization: `Bearer ${conn.apiKey}` };
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
  return `${base}/agents/${name}/ws?token=${encodeURIComponent(conn.apiKey)}`;
}
