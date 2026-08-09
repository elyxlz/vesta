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

export async function fetchTopModels(): Promise<OpenRouterModelOption[]> {
  return apiJson<OpenRouterModelOption[]>("/providers/openrouter/models/top");
}

// Vestad proxies the check to OpenRouter's /api/v1/key, throwing on 401.
// Going through vestad keeps the web and CLI paths symmetric: both clients
// call the same endpoint, and the validation logic lives in one place.
export async function validateKey(key: string): Promise<void> {
  await apiJson(
    "/providers/openrouter/validate-key",
    jsonInit("POST", { key }),
  );
}
