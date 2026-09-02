import * as core from "@vesta/core";
import { httpClient } from "./client";

// Bound to the app's one HttpClient so call sites keep their import path.
// LEGACY(remove-when: the chat-session epic points call sites at @vesta/core directly).

export type { FileReadResponse, FileTreeEntry } from "@vesta/core";

export const fetchFileTree = (agent: string) =>
  core.fetchFileTree(httpClient, agent);
export const readFile = (agent: string, path: string) =>
  core.readFile(httpClient, agent, path);
export const writeFile = (agent: string, path: string, content: string) =>
  core.writeFile(httpClient, agent, path, content);
