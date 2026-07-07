import { apiJson } from "./client";

export interface ContextPreset {
  tokens: number;
  label: string;
  note: string;
  // Plan tiers this preset is offered to; absent means every plan. The 1M/500K Claude windows carry
  // ["max"] because the 1M-context beta is a Max-only entitlement.
  plans?: string[];
}

export interface ProviderContext {
  default: number;
  presets: ContextPreset[];
  // Per-plan default window; the picker prefers this over `default` when it knows the plan tier.
  defaults_by_plan?: Record<string, number>;
}

export interface ProviderEntry {
  display: string;
  // Explicit model slugs (Claude) or the "live" sentinel (OpenRouter, fetched from its own endpoint).
  models: string[] | "live";
  default_model: string | null;
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

// The new-agent setup description served at GET /manifest: the per-provider catalog (`providers`),
// the new-agent defaults (`default_provider`, `default_personality`), and the personality presets
// (`personalities`, merged from the skill by vestad). The wizard/settings read it all from here.
export interface Manifest {
  default_provider: string;
  default_personality: string;
  providers: Record<string, ProviderEntry>;
  personalities: Personality[];
}

export async function fetchManifest(): Promise<Manifest> {
  return apiJson<Manifest>("/manifest");
}
