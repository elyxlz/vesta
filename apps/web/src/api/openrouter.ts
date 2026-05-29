import { apiJson } from "./client";

export interface OpenRouterModelOption {
  slug: string;
  label: string;
  author: string;
  context_length?: number;
}

export async function fetchTopOpenRouterModels(): Promise<
  OpenRouterModelOption[]
> {
  return apiJson<OpenRouterModelOption[]>("/openrouter/models/top");
}

// Vestad proxies the check to OpenRouter's /api/v1/key, throwing on 401.
// Going through vestad keeps the web and CLI paths symmetric: both clients
// call the same endpoint, and the validation logic lives in one place.
export async function validateOpenRouterKey(key: string): Promise<void> {
  await apiJson("/openrouter/validate-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
}
