import { apiJson, jsonInit } from "../client";
import type { OpenRouterModelOption } from "./openrouter";

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

// The live Claude catalog during onboarding: the browser holds the fresh OAuth blob and
// vestad calls the Anthropic Models API with it (the agent is not signed in yet).
export async function fetchClaudeModels(
  credentials: string,
): Promise<OpenRouterModelOption[]> {
  return apiJson<OpenRouterModelOption[]>(
    "/providers/claude/models",
    jsonInit("POST", { credentials }),
  );
}

// The live Claude catalog in settings: the agent is signed in, so it lists models from its own
// stored token; vestad relays the read.
export async function fetchAgentClaudeModels(
  agentName: string,
): Promise<OpenRouterModelOption[]> {
  return apiJson<OpenRouterModelOption[]>(
    `/agents/${encodeURIComponent(agentName)}/provider/models`,
  );
}
