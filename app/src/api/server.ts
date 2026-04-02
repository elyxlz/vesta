import { setConnection } from "@/lib/connection";

export async function connectToServer(
  url: string,
  apiKey: string,
): Promise<void> {
  const normalized = url.replace(/\/+$/, "");
  const resp = await fetch(`${normalized}/health`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  }).catch(() => null);
  if (!resp || !resp.ok) {
    throw new Error("could not reach server");
  }
  setConnection(normalized, apiKey);
}
