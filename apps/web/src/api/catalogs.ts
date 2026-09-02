import * as core from "@vesta/core";
import type {
  ProviderCatalog as CoreProviderCatalog,
  ProviderCatalogEntry,
  ProviderContextPolicy,
  ProviderContextPreset,
} from "@vesta/core";
import { httpClient } from "./client";

// Bound to the app's one HttpClient so call sites keep their import path.
// LEGACY(remove-when: the chat-session epic points call sites at @vesta/core directly).

export type ContextPreset = ProviderContextPreset;
export type ProviderContext = ProviderContextPolicy;
export type ProviderEntry = ProviderCatalogEntry;
export type ProviderCatalog = CoreProviderCatalog;
export type { Personality, PersonalityCatalog } from "@vesta/core";
export { contextForModel } from "@vesta/core";

export const fetchProviderCatalog = (agentName: string) =>
  core.fetchProviderCatalog(httpClient, agentName);
export const fetchPersonalities = (agentName: string) =>
  core.fetchPersonalities(httpClient, agentName);
