import { jsonInit, type HttpClient } from "../transport/http";
import { agentPath } from "./agents";

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

export async function fetchFileTree(
  http: HttpClient,
  name: string,
): Promise<FileTreeEntry[]> {
  const response = await http.json<{
    tree: string[];
    entries?: FileTreeEntry[];
  }>(agentPath(name, "/tree"));
  return (
    response.entries ??
    response.tree.map((path) => ({ path, is_dir: false, mode: 0o644 }))
  );
}

export async function readFile(
  http: HttpClient,
  name: string,
  path: string,
): Promise<FileReadResponse> {
  const query = new URLSearchParams({ path }).toString();
  return http.json<FileReadResponse>(agentPath(name, `/file?${query}`));
}

export async function writeFile(
  http: HttpClient,
  name: string,
  path: string,
  content: string,
): Promise<void> {
  await http.request(
    agentPath(name, "/file"),
    jsonInit("PUT", { path, content }),
  );
}
