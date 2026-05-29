import { apiJson } from "./client";

export interface AuthStartResult {
  auth_url: string;
  session_id: string;
}

// Per-agent OAuth — used to reauthenticate an existing agent.
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

// Agent-less OAuth — used by the new-agent wizard so credentials are obtained
// before the agent exists, then passed into POST /agents at create time.
export async function startAuth(): Promise<AuthStartResult> {
  return apiJson("/auth/start", { method: "POST" });
}

export async function completeAuth(
  sessionId: string,
  code: string,
): Promise<string> {
  const resp = await apiJson<{ credentials: string }>("/auth/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, code }),
  });
  return resp.credentials;
}
