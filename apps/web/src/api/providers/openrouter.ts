import * as core from "@vesta/core";
import { httpClient } from "../client";

// Bound to the app's one HttpClient so call sites keep their import path.
// LEGACY(remove-when: the chat-session epic points call sites at @vesta/core directly).

export type { OpenRouterModelOption } from "@vesta/core";

export const fetchTopModels = (agentName: string) =>
  core.fetchOpenRouterModels(httpClient, agentName);
export const validateKey = (agentName: string, key: string) =>
  core.validateOpenRouterKey(httpClient, agentName, key);
