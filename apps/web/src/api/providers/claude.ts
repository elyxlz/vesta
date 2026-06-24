import { apiJson, jsonInit } from "../client";

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
    jsonInit("POST", { session_id: sessionId, code }),
  );
  return resp.credentials;
}

export interface ClaudeModelOption {
  /// The alias stored in AGENT_MODEL, e.g. "opus".
  id: string;
  label: string;
  note: string;
}

/// The curated Claude model list, served by vestad (opus / sonnet / haiku).
export async function fetchModels(): Promise<ClaudeModelOption[]> {
  return apiJson<ClaudeModelOption[]>("/providers/claude/models");
}
