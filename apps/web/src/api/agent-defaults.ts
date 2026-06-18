import { apiJson } from "./client";

export interface ContextPreset {
  tokens: number;
  label: string;
  note: string;
}

// Creation-time defaults a new agent gets. vestad owns these (vestad/src/defaults.rs);
// the wizard reads them here instead of hardcoding its own copies.
export interface AgentDefaults {
  personality: string;
  provider: string;
  model: string;
  context_tokens: number;
  context_presets: ContextPreset[];
}

export async function fetchAgentDefaults(): Promise<AgentDefaults> {
  return apiJson<AgentDefaults>("/agent-defaults");
}
