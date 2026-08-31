import { apiJson, jsonInit } from "../client";

export interface OAuthStartResult {
  auth_url: string;
  user_code: string;
  session_id: string;
}

export async function startOAuth(agentName: string): Promise<OAuthStartResult> {
  return apiJson(
    `/agents/${encodeURIComponent(agentName)}/providers/openai/oauth/start`,
    { method: "POST" },
  );
}

export async function completeOAuth(
  agentName: string,
  sessionId: string,
): Promise<string> {
  const response = await apiJson<{ credentials: string }>(
    `/agents/${encodeURIComponent(agentName)}/providers/openai/oauth/complete`,
    jsonInit("POST", { session_id: sessionId }),
  );
  return response.credentials;
}
