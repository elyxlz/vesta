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

// Hits OpenRouter's /api/v1/key endpoint with the user's key. 200 = valid auth,
// 401 = bad key. CORS-allowed so the browser can call it directly — the key
// never goes through vestad, just from the user's browser to OpenRouter.
const OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key";

export async function validateOpenRouterKey(key: string): Promise<void> {
  const resp = await fetch(OPENROUTER_KEY_URL, {
    headers: { Authorization: `Bearer ${key}` },
  });
  if (resp.status === 401) {
    throw new Error("invalid API key");
  }
  if (!resp.ok) {
    throw new Error(`openrouter returned HTTP ${resp.status}`);
  }
}
