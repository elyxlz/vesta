import { invoke, Channel } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { check } from "@tauri-apps/plugin-updater";
import { detectPlatform } from "./platform";
import type { AgentInfo, ListEntry, LogEvent } from "./types";

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const resp = await fetch(apiUrl(path), {
    ...init,
    headers: { ...authHeaders(), ...init?.headers },
  });
  if (!resp.ok) {
    const body = await resp.text();
    let msg: string;
    try {
      msg = JSON.parse(body).error ?? body;
    } catch {
      msg = body;
    }
    throw new Error(msg);
  }
  return resp;
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await apiFetch(path, init);
  return resp.json();
}

export function isNewer(latest: string, current: string): boolean {
  const a = latest.split(".").map(Number);
  const b = current.split(".").map(Number);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i] ?? 0) > (b[i] ?? 0)) return true;
    if ((a[i] ?? 0) < (b[i] ?? 0)) return false;
  }
  return false;
}

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
  await apiJson(`/agents/${encodeURIComponent(name)}/start`, { method: "POST" });
}

export async function stopAgent(name: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/stop`, { method: "POST" });
}

export async function restartAgent(name: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/restart`, { method: "POST" });
}

export async function deleteAgent(name: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/destroy`, { method: "POST" });
}

export async function rebuildAgent(name: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/rebuild`, { method: "POST" });
}

export async function backupAgent(name: string): Promise<void> {
  const resp = await apiFetch(`/agents/${encodeURIComponent(name)}/backup`, { method: "POST" });
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

export async function restoreAgent(file: File, name?: string, replace?: boolean): Promise<void> {
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

export async function waitForReady(name: string, timeout?: number): Promise<void> {
  const t = timeout ?? 30;
  await apiJson(`/agents/${encodeURIComponent(name)}/wait-ready?timeout=${t}`);
}

const logSources = new Map<string, EventSource>();

export function streamLogs(
  name: string,
  onEvent: (event: LogEvent) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const conn = getConnection();
    if (!conn) { reject(new Error("not connected")); return; }

    const url = `${conn.url}/agents/${encodeURIComponent(name)}/logs?token=${encodeURIComponent(conn.apiKey)}`;
    const es = new EventSource(url);
    logSources.set(name, es);

    es.onmessage = (e) => {
      const text = e.data;
      if (text.startsWith("error:")) {
        onEvent({ kind: "Error", message: text });
      } else {
        onEvent({ kind: "Line", text });
      }
    };

    es.addEventListener("agent_stopped", () => {
      onEvent({ kind: "End" });
      es.close();
      logSources.delete(name);
      resolve();
    });

    es.onerror = () => {
      onEvent({ kind: "Error", message: "log stream disconnected" });
      es.close();
      logSources.delete(name);
      resolve();
    };
  });
}

export async function stopLogs(name: string): Promise<void> {
  const es = logSources.get(name);
  if (es) {
    es.close();
    logSources.delete(name);
  }
}

export interface AuthStartResult {
  auth_url: string;
  session_id: string;
}

export async function authenticate(name: string): Promise<AuthStartResult> {
  return apiJson(`/agents/${encodeURIComponent(name)}/auth`, { method: "POST" });
}

export async function submitAuthCode(name: string, sessionId: string, code: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/auth/code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, code }),
  });
}

export async function agentHost(): Promise<string> {
  const conn = getConnection();
  return conn?.url ?? "";
}

export async function connectToServer(url: string, apiKey: string): Promise<void> {
  const normalized = url.replace(/\/+$/, "");
  const resp = await fetch(`${normalized}/health`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  }).catch(() => null);
  if (!resp || !resp.ok) {
    throw new Error("could not reach server");
  }
  setConnection(normalized, apiKey);
}

export async function autoSetup(): Promise<boolean> {
  if (!isTauri) return true;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke("auto_setup");
}


export async function runInstallScript(version: string): Promise<void> {
  if (!isTauri) return;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke("run_install_script", { version });
}

export async function checkAndInstallUpdate(): Promise<{ version: string; installing: boolean } | null> {
  if (!isTauri) return null;
  try {
    const { getVersion } = await import("@tauri-apps/api/app");
    const { detectPlatform } = await import("./platform");
    if (detectPlatform() === "linux") {
      const current = await getVersion();
      const resp = await fetch("https://api.github.com/repos/elyxlz/vesta/releases/latest");
      if (!resp.ok) return null;
      const data = await resp.json();
      const latest = (data.tag_name as string).replace(/^v/, "");
      if (!isNewer(latest, current)) return null;
      return { version: latest, installing: false };
    }
    const { check } = await import("@tauri-apps/plugin-updater");
    const update = await check();
    if (!update) return null;
    await update.downloadAndInstall();
    return { version: update.version, installing: true };
  } catch (e) {
    console.error("Update check failed:", e);
    return null;
  }
}
