import { writable } from "svelte/store";
import type { AgentInfo } from "./types";

export const agent = writable<AgentInfo | null>(null);
export const agentName = writable<string>("vesta");
