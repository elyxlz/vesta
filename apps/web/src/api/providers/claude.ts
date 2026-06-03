import { apiJson } from "../client";

export interface OAuthStartResult {
  auth_url: string;
  session_id: string;
}

// Standalone OAuth: runs the PKCE dance through vestad without binding to an
// agent. The caller passes the returned credentials to createAgent (new agent)
// or setProvider (existing agent).
export async function startOAuth(): Promise<OAuthStartResult> {
  return apiJson("/providers/claude/oauth/start", { method: "POST" });
}

export async function completeOAuth(
  sessionId: string,
  code: string,
): Promise<string> {
  const resp = await apiJson<{ credentials: string }>(
    "/providers/claude/oauth/complete",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, code }),
    },
  );
  return resp.credentials;
}
