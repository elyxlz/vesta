import * as core from "@vesta/core";
import { httpClient } from "../client";

// Bound to the app's one HttpClient so call sites keep their import path.
// LEGACY(remove-when: the chat-session epic points call sites at @vesta/core directly).

export type { ClaudeOAuthStart as OAuthStartResult } from "@vesta/core";

export const startOAuth = (agentName: string) =>
  core.startClaudeOAuth(httpClient, agentName);
export const completeOAuth = (
  agentName: string,
  sessionId: string,
  code: string,
) => core.completeClaudeOAuth(httpClient, agentName, sessionId, code);
export const fetchClaudeModels = (agentName: string, credentials: string) =>
  core.fetchClaudeModelsWithCredentials(httpClient, agentName, credentials);
export const fetchAgentClaudeModels = (agentName: string) =>
  core.fetchAgentClaudeModels(httpClient, agentName);
