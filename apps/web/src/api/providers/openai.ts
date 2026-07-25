import { apiJson, jsonInit } from "../client";

export interface OAuthStartResult {
  auth_url: string;
  user_code: string;
  session_id: string;
}

export async function startOAuth(): Promise<OAuthStartResult> {
  return apiJson("/providers/openai/oauth/start", { method: "POST" });
}

export async function completeOAuth(sessionId: string): Promise<string> {
  const response = await apiJson<{ credentials: string }>(
    "/providers/openai/oauth/complete",
    jsonInit("POST", { session_id: sessionId }),
  );
  return response.credentials;
}
