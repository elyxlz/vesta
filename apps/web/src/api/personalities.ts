import { apiJson } from "./client";

export interface Personality {
  name: string;
  title: string;
  emoji: string;
  description: string;
  active: boolean;
}

export async function fetchPersonalities(
  agentName: string,
): Promise<Personality[]> {
  const { personalities } = await apiJson<{ personalities: Personality[] }>(
    `/agents/${encodeURIComponent(agentName)}/personalities`,
  );
  return personalities;
}

export async function applyPersonality(
  agentName: string,
  name: string,
): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(agentName)}/personality/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}
