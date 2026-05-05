import { apiJson } from "./client";

export interface FileTreeEntry {
  path: string;
  is_dir: boolean;
  mode: number;
}

export interface FileReadResponse {
  path: string;
  content: string;
  encoding: "utf-8" | "base64";
  readonly: boolean;
  mode: number;
  size: number;
  is_dir: boolean;
}

export async function fetchFileTree(agent: string): Promise<FileTreeEntry[]> {
  const data = await apiJson<{ tree: string[]; entries?: FileTreeEntry[] }>(
    `/agents/${encodeURIComponent(agent)}/tree`,
  );
  return (
    data.entries ??
    data.tree.map((path) => ({ path, is_dir: false, mode: 0o644 }))
  );
}

export async function readFile(
  agent: string,
  path: string,
): Promise<FileReadResponse> {
  const qs = new URLSearchParams({ path }).toString();
  return apiJson<FileReadResponse>(
    `/agents/${encodeURIComponent(agent)}/file?${qs}`,
  );
}

export async function writeFile(
  agent: string,
  path: string,
  content: string,
): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(agent)}/file`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
}
