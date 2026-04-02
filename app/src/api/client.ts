import { apiUrl, authHeaders } from "@/lib/connection";

export async function apiFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const resp = await fetch(apiUrl(path), {
    ...init,
    headers: { ...authHeaders(), ...init?.headers },
  });
  if (!resp.ok) {
    const body = await resp.text();
    let msg: string;
    try {
      msg = JSON.parse(body).error ?? body;
    } catch {
      msg = body;
    }
    throw new Error(msg);
  }
  return resp;
}

export async function apiJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const resp = await apiFetch(path, init);
  return resp.json();
}
