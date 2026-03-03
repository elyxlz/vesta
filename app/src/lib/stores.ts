import { writable } from "svelte/store";
import type { AgentInfo } from "./types";
export { agentState, messages, connected, resetReconnect } from "./ws";

export const agent = writable<AgentInfo | null>(null);

const AGENT_NAME_KEY = "vesta:agent-name";
const storedName = typeof localStorage !== "undefined"
  ? localStorage.getItem(AGENT_NAME_KEY) ?? "vesta"
  : "vesta";

export const agentName = writable<string>(storedName);

agentName.subscribe((name) => {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(AGENT_NAME_KEY, name);
  }
});
