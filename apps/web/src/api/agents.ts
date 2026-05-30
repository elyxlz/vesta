import { apiJson, apiFetch } from "./client";

export interface OpenRouterConfig {
  key: string;
  model: string;
  zdr: boolean;
}

export type ProviderResult =
  | { kind: "claude"; credentials: string }
  | { kind: "openrouter"; config: OpenRouterConfig };

/// Switch (or refresh) an existing agent's provider. Mirrors createAgent's body:
/// either `credentials` (Claude OAuth blob) or `openrouter_*` fields. Vestad
/// injects the config, clears the obsolete file if needed, and restarts the agent.
export async function setProvider(
  name: string,
  result: ProviderResult,
): Promise<void> {
  const body =
    result.kind === "claude"
      ? { credentials: result.credentials }
      : {
          openrouter_key: result.config.key,
          openrouter_model: result.config.model,
          openrouter_zdr: result.config.zdr,
        };
  await apiFetch(`/agents/${encodeURIComponent(name)}/provider`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/// Create an empty agent container. Provider config is sent separately via
/// `setProvider` once the agent is up — vestad no longer accepts credentials
/// at create time (the agent owns its own auth state).
export async function createAgent(
  name: string,
  seedPersonality?: string,
): Promise<void> {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  await apiJson("/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, timezone, seed_personality: seedPersonality }),
  });
}

/// Poll /agents/{name} until it reports "alive" or "not_authenticated".
/// A brand-new empty agent boots into not_authenticated until provisioned.
export async function waitUntilRunning(
  name: string,
  timeoutMs: number,
  pollIntervalMs = 500,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const resp = await apiJson<{ status: string }>(
      `/agents/${encodeURIComponent(name)}`,
    );
    if (resp.status === "alive" || resp.status === "not_authenticated") return;
    if (resp.status === "dead" || resp.status === "stopped" || resp.status === "not_found") {
      throw new Error(`${name}: ${resp.status}`);
    }
    await new Promise((r) => setTimeout(r, pollIntervalMs));
  }
  throw new Error(`${name}: timed out waiting for HTTP server`);
}

export async function waitUntilAlive(
  name: string,
  timeoutMs: number,
  pollIntervalMs = 500,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const resp = await apiJson<{ status: string }>(
      `/agents/${encodeURIComponent(name)}`,
    );
    if (resp.status === "alive") return;
    if (resp.status === "dead" || resp.status === "stopped" || resp.status === "not_found" || resp.status === "not_authenticated") {
      throw new Error(`${name}: ${resp.status}`);
    }
    await new Promise((r) => setTimeout(r, pollIntervalMs));
  }
  throw new Error(`${name}: timed out waiting to become alive`);
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

export interface BackupInfo {
  id: string;
  agent_name: string;
  backup_type: string;
  created_at: string;
  size: number;
}

export async function createBackup(name: string): Promise<BackupInfo> {
  return apiJson(`/agents/${encodeURIComponent(name)}/backups`, {
    method: "POST",
  });
}

export async function listBackups(name: string): Promise<BackupInfo[]> {
  return apiJson(`/agents/${encodeURIComponent(name)}/backups`);
}

export async function restoreBackup(
  name: string,
  backupId: string,
): Promise<void> {
  await apiJson(
    `/agents/${encodeURIComponent(name)}/backups/${encodeURIComponent(backupId)}/restore`,
    { method: "POST" },
  );
}

export async function deleteBackup(
  name: string,
  backupId: string,
): Promise<void> {
  await apiJson(
    `/agents/${encodeURIComponent(name)}/backups/${encodeURIComponent(backupId)}`,
    { method: "DELETE" },
  );
}

export interface RateLimit {
  utilization: number | null;
  resets_at: string | null;
}

export interface ExtraUsage {
  is_enabled: boolean;
  monthly_limit: number | null;
  used_credits: number | null;
  utilization: number | null;
}

export interface Utilization {
  five_hour?: RateLimit | null;
  seven_day?: RateLimit | null;
  seven_day_oauth_apps?: RateLimit | null;
  seven_day_opus?: RateLimit | null;
  seven_day_sonnet?: RateLimit | null;
  extra_usage?: ExtraUsage | null;
}

export async function fetchUsage(name: string): Promise<Utilization> {
  return apiJson(`/agents/${encodeURIComponent(name)}/usage`);
}
