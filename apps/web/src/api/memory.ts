import { apiJson } from "./client";

export async function fetchMemory(agentName: string): Promise<string> {
  const { content } = await apiJson<{ content: string }>(
    `/agents/${encodeURIComponent(agentName)}/memory`,
  );
  return content;
}

export async function saveMemory(
  agentName: string,
  content: string,
): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(agentName)}/memory`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}
