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
