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

export interface Personality {
  name: string;
  emoji: string;
  title: string;
  description: string;
  sample: string;
  order: number;
}

// The whole new-agent setup description, generated from the agent's models + shipped skills and served
// at GET /manifest: every settable pref's default (`prefs`), the per-provider catalog (`providers`),
// and the personality presets (`personalities`). The wizard/settings read it all from here.
export interface Manifest {
  default_provider: string;
  prefs: Record<string, string | number | boolean | null>;
  providers: Record<string, ProviderEntry>;
  personalities: Personality[];
}

export async function fetchManifest(): Promise<Manifest> {
  return apiJson<Manifest>("/manifest");
}
