import { apiJson, jsonInit } from "../client";

export interface OpenRouterModelOption {
  slug: string;
  label: string;
  author: string;
  context_length?: number;
  // USD per million prompt/completion/cache-read tokens, when OpenRouter reports it.
  input_price?: number | null;
  output_price?: number | null;
  cache_read_price?: number | null;
}

export async function fetchTopModels(
  agentName: string,
): Promise<OpenRouterModelOption[]> {
  return apiJson<OpenRouterModelOption[]>(
    `/agents/${encodeURIComponent(agentName)}/providers/openrouter/models/top`,
  );
}

// The target agent checks OpenRouter's /api/v1/key, throwing on 401. Both
// clients use this agent-owned path, so validation still has one owner.
export async function validateKey(
  agentName: string,
  key: string,
): Promise<void> {
  await apiJson(
    `/agents/${encodeURIComponent(agentName)}/providers/openrouter/validate-key`,
    jsonInit("POST", { key }),
  );
}
