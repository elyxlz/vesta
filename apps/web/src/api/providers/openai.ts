import * as core from "@vesta/core";
import { httpClient } from "../client";

// Bound to the app's one HttpClient so call sites keep their import path.
// LEGACY(remove-when: the chat-session epic points call sites at @vesta/core directly).

export type { OpenAIOAuthStart as OAuthStartResult } from "@vesta/core";

export const startOAuth = (agentName: string) =>
  core.startOpenAIOAuth(httpClient, agentName);
export const completeOAuth = (agentName: string, sessionId: string) =>
  core.completeOpenAIOAuth(httpClient, agentName, sessionId);
