import type {
  ProviderCatalog,
  ProviderCatalogEntry,
  ProviderContextPolicy,
} from "../provider/provider";
import type { HttpClient } from "../transport/http";
import { agentPath } from "./agents";

export interface Personality {
  name: string;
  emoji: string;
  title: string;
  description: string;
  sample: string;
  order: number;
}

// Provider setup metadata is owned by each running agent and projected by GET /provider.
// Personality presets are a separate agent-owned catalog (GET /personalities).
export interface PersonalityCatalog {
  default: string;
  presets: Personality[];
}

export function contextForModel(
  entry: ProviderCatalogEntry | undefined,
  model: string,
): ProviderContextPolicy | undefined {
  return entry?.context_by_model?.[model] ?? entry?.context;
}

export async function fetchProviderCatalog(
  http: HttpClient,
  name: string,
): Promise<ProviderCatalog> {
  const resource = await http.json<{ catalog: ProviderCatalog }>(
    agentPath(name, "/provider"),
  );
  return resource.catalog;
}

export async function fetchPersonalities(
  http: HttpClient,
  name: string,
): Promise<PersonalityCatalog> {
  return http.json<PersonalityCatalog>(agentPath(name, "/personalities"));
}
