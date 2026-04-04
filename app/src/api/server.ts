import { setConnection } from "@/lib/connection";

export async function connectToServer(
  url: string,
  apiKey: string,
): Promise<void> {
  const normalized = url.replace(/\/+$/, "");

  const healthResp = await fetch(`${normalized}/health`).catch(() => null);
  if (!healthResp || !healthResp.ok) {
    throw new Error("could not reach server");
  }

  const resp = await fetch(`${normalized}/auth/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });

  if (!resp.ok) {
    throw new Error(resp.status === 401 ? "invalid API key" : "session creation failed");
  }

  const data = await resp.json();
  setConnection(normalized, data.access_token, data.refresh_token, data.expires_in);
}
