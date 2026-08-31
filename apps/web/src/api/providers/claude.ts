import { apiJson, jsonInit } from "../client";
import type { OpenRouterModelOption } from "./openrouter";

export interface OAuthStartResult {
  auth_url: string;
  session_id: string;
}

export async function startOAuth(agentName: string): Promise<OAuthStartResult> {
  return apiJson(
    `/agents/${encodeURIComponent(agentName)}/providers/claude/oauth/start`,
    { method: "POST" },
  );
}

export async function completeOAuth(
  agentName: string,
  sessionId: string,
  code: string,
): Promise<string> {
  const resp = await apiJson<{ credentials: string }>(
    `/agents/${encodeURIComponent(agentName)}/providers/claude/oauth/complete`,
    jsonInit("POST", { session_id: sessionId, code }),
  );
  return resp.credentials;
}

// The live Claude catalog during onboarding: the browser holds the fresh OAuth blob and
// the target agent calls the Anthropic Models API with it before storing anything.
export async function fetchClaudeModels(
  agentName: string,
  credentials: string,
): Promise<OpenRouterModelOption[]> {
  return apiJson<OpenRouterModelOption[]>(
    `/agents/${encodeURIComponent(agentName)}/providers/claude/models`,
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
