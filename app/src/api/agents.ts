import type { AgentInfo, ListEntry } from "@/lib/types";
import { apiFetch, apiJson } from "./client";

export async function listAgents(): Promise<ListEntry[]> {
  return apiJson("/agents");
}

export async function agentStatus(name: string): Promise<AgentInfo> {
  return apiJson(`/agents/${encodeURIComponent(name)}`);
}

export async function createAgent(name: string): Promise<void> {
  await apiJson("/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function startAgent(name: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/start`, {
    method: "POST",
  });
}

export async function stopAgent(name: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/stop`, {
    method: "POST",
  });
}

export async function restartAgent(name: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/restart`, {
    method: "POST",
  });
}

export async function deleteAgent(name: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/destroy`, {
    method: "POST",
  });
}

export async function rebuildAgent(name: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/rebuild`, {
    method: "POST",
  });
}

export async function backupAgent(name: string): Promise<void> {
  const resp = await apiFetch(
    `/agents/${encodeURIComponent(name)}/backup`,
    { method: "POST" },
  );
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name}.tar.gz`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function restoreAgent(
  file: File,
  name?: string,
  replace?: boolean,
): Promise<void> {
  const params = new URLSearchParams();
  if (name) params.set("name", name);
  if (replace) params.set("replace", "true");
  const qs = params.toString();
  await apiFetch(`/agents/restore${qs ? `?${qs}` : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/gzip" },
    body: file,
  });
}

export async function waitForReady(
  name: string,
  timeout?: number,
): Promise<void> {
  const t = timeout ?? 30;
  await apiJson(
    `/agents/${encodeURIComponent(name)}/wait-ready?timeout=${t}`,
  );
}

export async function waitForStopped(
  name: string,
  timeout = 30,
): Promise<void> {
  const deadline = Date.now() + timeout * 1000;
  while (Date.now() < deadline) {
    const info: AgentInfo = await agentStatus(name);
    if (info.status === "stopped") return;
    await new Promise((r) => setTimeout(r, 1000));
  }
}
