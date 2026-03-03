import { writable } from "svelte/store";
import type { AgentInfo } from "./types";
export { agentState, messages, connected, resetReconnect } from "./ws";

export const agent = writable<AgentInfo | null>(null);

export const agentName = writable<string>("vesta");
