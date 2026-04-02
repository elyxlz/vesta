import { getConnection } from "./connection";

export const appVersion: Promise<string> = (async () => {
  try {
    const conn = getConnection();
    if (!conn) return "unknown";
    const resp = await fetch(`${conn.url}/version`, {
      headers: { Authorization: `Bearer ${conn.apiKey}` },
    });
    if (!resp.ok) return "unknown";
    const data = await resp.json();
    return data.version ?? "unknown";
  } catch {
    return "unknown";
  }
})();
