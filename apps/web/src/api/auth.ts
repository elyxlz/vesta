import { apiJson } from "./client";

export interface AuthStartResult {
  auth_url: string;
  session_id: string;
}

export async function authenticate(name: string): Promise<AuthStartResult> {
  return apiJson(`/agents/${encodeURIComponent(name)}/auth`, {
    method: "POST",
  });
}

export async function submitAuthCode(
  name: string,
  sessionId: string,
  code: string,
): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/auth/code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, code }),
  });
}
