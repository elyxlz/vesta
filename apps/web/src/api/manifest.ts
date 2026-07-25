import { apiJson } from "./client";
import type {
  ProviderContextPolicy,
  ProviderContextPreset,
  ProviderManifest,
  ProviderManifestEntry,
} from "@vesta/core";

export type ContextPreset = ProviderContextPreset;
export type ProviderContext = ProviderContextPolicy;
export type ProviderEntry = ProviderManifestEntry;

export function contextForModel(
  entry: ProviderEntry | undefined,
  model: string,
): ProviderContext | undefined {
  return entry?.context_by_model?.[model] ?? entry?.context;
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
export interface Manifest extends ProviderManifest {
  personalities: Personality[];
}

export async function fetchManifest(): Promise<Manifest> {
  return apiJson<Manifest>("/manifest");
}
