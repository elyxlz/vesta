import {
  RESTART_REASONS,
  type RestartReason,
} from "../lifecycle/restart-reasons";
import {
  normalizeProviderInfo,
  providerPutBody,
  type ProviderCatalog,
  type ProviderInfo,
  type ProviderInfoWire,
  type ProviderSelection,
} from "../provider/provider";
import { jsonInit, type HttpClient } from "../transport/http";
import { agentPath, restartAgent } from "./agents";

export interface ProviderResource {
  provider: ProviderInfo;
  catalog: ProviderCatalog;
}

// Provision or re-attach a provider: PUT /provider with the chosen selection, write any prefs
// (personality, timezone) to PUT /config, then restart once to apply. Re-provisioning an existing
// agent omits timezone and personality to keep the agent's own.
export async function provisionAgent(
  http: HttpClient,
  name: string,
  selection: ProviderSelection,
  personality?: string,
  timezone?: string,
): Promise<void> {
  await http.request(
    agentPath(name, "/provider"),
    jsonInit("PUT", providerPutBody(selection)),
  );
  const prefs: Record<string, string> = {};
  if (personality) prefs.agent_personality = personality;
  if (timezone) prefs.timezone = timezone;
  if (Object.keys(prefs).length > 0) {
    await http.request(agentPath(name, "/config"), jsonInit("PUT", prefs));
  }
  await restartAgent(http, name, RESTART_REASONS.provider);
}

// Sign out: clear the agent's provider credentials (DELETE /provider), then restart so it boots
// not_authenticated.
export async function signOutProvider(
  http: HttpClient,
  name: string,
): Promise<void> {
  await http.request(agentPath(name, "/provider"), { method: "DELETE" });
  await restartAgent(http, name, RESTART_REASONS.signOut);
}

// Read an agent's active provider from its GET /provider. The agent reports `kind` only when a
// provider is chosen (omitted when unprovisioned) plus an `authed` flag, so a client can tell "no
// provider yet" (kind "none") apart from "chosen but credential expired" (kind set, authed false).
export async function getProvider(
  http: HttpClient,
  name: string,
): Promise<ProviderResource> {
  const resource = await http.json<
    ProviderInfoWire & { catalog: ProviderCatalog }
  >(agentPath(name, "/provider"));
  return {
    provider: normalizeProviderInfo(resource),
    catalog: resource.catalog,
  };
}

async function patchProvider(
  http: HttpClient,
  name: string,
  patch: Record<string, unknown>,
  reason: RestartReason,
): Promise<void> {
  await http.request(agentPath(name, "/provider"), jsonInit("PATCH", patch));
  await restartAgent(http, name, reason);
}

// Change only the model. Vestad restarts the agent so it takes effect.
export async function setModel(
  http: HttpClient,
  name: string,
  model: string,
): Promise<void> {
  await patchProvider(http, name, { model }, RESTART_REASONS.model);
}

// Change only the context window. Vestad restarts the agent so it takes effect.
export async function setContextWindow(
  http: HttpClient,
  name: string,
  maxContextTokens: number,
): Promise<void> {
  await patchProvider(
    http,
    name,
    { max_context_tokens: maxContextTokens },
    RESTART_REASONS.context,
  );
}

// The provider setup routes the agent serves and vestad relays at /agents/{name}/providers/...:
// OAuth sessions, live model catalogs, and key validation, each owned by the target agent.
function providerSetupPath(name: string, suffix: string): string {
  return agentPath(name, `/providers/${suffix}`);
}

export interface OpenRouterModelOption {
  slug: string;
  label: string;
  author: string;
  note?: string;
  context_length?: number;
  // USD per million prompt, completion, and cache-read tokens, when the provider reports it.
  input_price?: number | null;
  output_price?: number | null;
  cache_read_price?: number | null;
}

export interface ClaudeOAuthStart {
  auth_url: string;
  session_id: string;
}

export interface OpenAIOAuthStart {
  auth_url: string;
  user_code: string;
  session_id: string;
}

export async function startClaudeOAuth(
  http: HttpClient,
  name: string,
): Promise<ClaudeOAuthStart> {
  return http.json<ClaudeOAuthStart>(
    providerSetupPath(name, "claude/oauth/start"),
    {
      method: "POST",
    },
  );
}

export async function completeClaudeOAuth(
  http: HttpClient,
  name: string,
  sessionId: string,
  code: string,
): Promise<string> {
  const result = await http.json<{ credentials: string }>(
    providerSetupPath(name, "claude/oauth/complete"),
    jsonInit("POST", { session_id: sessionId, code }),
  );
  return result.credentials;
}

// The live Claude catalog during onboarding: the client holds the fresh OAuth blob and the target
// agent calls the Anthropic Models API with it before storing anything.
export async function fetchClaudeModelsWithCredentials(
  http: HttpClient,
  name: string,
  credentials: string,
): Promise<OpenRouterModelOption[]> {
  return http.json<OpenRouterModelOption[]>(
    providerSetupPath(name, "claude/models"),
    jsonInit("POST", { credentials }),
  );
}

// The live Claude catalog in settings: the agent is signed in, so it lists models from its own
// stored token; vestad relays the read.
export async function fetchAgentClaudeModels(
  http: HttpClient,
  name: string,
): Promise<OpenRouterModelOption[]> {
  return http.json<OpenRouterModelOption[]>(
    agentPath(name, "/provider/models"),
  );
}

export async function startOpenAIOAuth(
  http: HttpClient,
  name: string,
): Promise<OpenAIOAuthStart> {
  return http.json<OpenAIOAuthStart>(
    providerSetupPath(name, "openai/oauth/start"),
    {
      method: "POST",
    },
  );
}

export async function completeOpenAIOAuth(
  http: HttpClient,
  name: string,
  sessionId: string,
): Promise<string> {
  const result = await http.json<{ credentials: string }>(
    providerSetupPath(name, "openai/oauth/complete"),
    jsonInit("POST", { session_id: sessionId }),
  );
  return result.credentials;
}

export async function fetchOpenRouterModels(
  http: HttpClient,
  name: string,
): Promise<OpenRouterModelOption[]> {
  return http.json<OpenRouterModelOption[]>(
    providerSetupPath(name, "openrouter/models/top"),
  );
}

// The target agent checks OpenRouter's /api/v1/key, throwing on 401, so validation has one owner.
export async function validateOpenRouterKey(
  http: HttpClient,
  name: string,
  key: string,
): Promise<void> {
  await http.request(
    providerSetupPath(name, "openrouter/validate-key"),
    jsonInit("POST", { key }),
  );
}
