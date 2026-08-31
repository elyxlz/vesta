import { apiJson } from "./client";
import type {
  ProviderContextPolicy,
  ProviderContextPreset,
  ProviderCatalog as CoreProviderCatalog,
  ProviderCatalogEntry,
} from "@vesta/core";

export type ContextPreset = ProviderContextPreset;
export type ProviderContext = ProviderContextPolicy;
export type ProviderEntry = ProviderCatalogEntry;

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

// Provider setup metadata is owned by each running agent and projected by GET /provider.
// Personality presets remain a separate agent-owned catalog.
export type ProviderCatalog = CoreProviderCatalog;

export interface PersonalityCatalog {
  default: string;
  presets: Personality[];
}

export interface AgentCatalogs {
  providers: ProviderCatalog;
  personalities: PersonalityCatalog;
}

export async function fetchProviderCatalog(
  agentName: string,
): Promise<ProviderCatalog> {
  const resource = await apiJson<{ catalog: ProviderCatalog }>(
    `/agents/${encodeURIComponent(agentName)}/provider`,
  );
  return resource.catalog;
}

export async function fetchPersonalities(
  agentName: string,
): Promise<PersonalityCatalog> {
  return apiJson<PersonalityCatalog>(
    `/agents/${encodeURIComponent(agentName)}/personalities`,
  );
}

export async function fetchAgentCatalogs(
  agentName: string,
): Promise<AgentCatalogs> {
  const [providers, personalities] = await Promise.all([
    fetchProviderCatalog(agentName),
    fetchPersonalities(agentName),
  ]);
  return { providers, personalities };
}
