import { apiJson } from "./client";

export interface ContextPreset {
  tokens: number;
  label: string;
  note: string;
}

export interface ProviderContext {
  min: number;
  max: number;
  default: number;
  presets: ContextPreset[];
}

export interface ProviderEntry {
  kind: string;
  display: string;
  // Explicit model slugs (Claude) or the "live" sentinel (OpenRouter, fetched from its own endpoint).
  models: string[] | "live";
  default_model: string | null;
  thinking_supported: boolean;
  context: ProviderContext;
}

// The provider manifest: per-provider catalog + new-agent defaults, generated from the agent's
// models and served at GET /manifest. The wizard/settings read catalogs + defaults here instead of
// hardcoding their own copies.
export interface Manifest {
  default_provider: string;
  agent_personality: string;
  providers: Record<string, ProviderEntry>;
}

export async function fetchManifest(): Promise<Manifest> {
  return apiJson<Manifest>("/manifest");
}
