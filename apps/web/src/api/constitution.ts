import { apiJson, jsonInit } from "./client";

export async function fetchConstitution(agentName: string): Promise<string> {
  const { content } = await apiJson<{ content: string }>(
    `/agents/${encodeURIComponent(agentName)}/constitution`,
  );
  return content;
}

export async function saveConstitution(
  agentName: string,
  content: string,
): Promise<void> {
  await apiJson(
    `/agents/${encodeURIComponent(agentName)}/constitution`,
    jsonInit("PUT", { content }),
  );
}
