import { apiJson, apiFetch } from "./client";

export interface OpenRouterConfig {
  key: string;
  model: string;
}

export type ProviderResult =
  | {
      kind: "claude";
      credentials: string;
      model?: string;
      maxContextTokens?: number;
    }
  | {
      kind: "openrouter";
      config: OpenRouterConfig;
      maxContextTokens?: number;
    };

/// Set an agent's provider credentials (Claude OAuth blob or OpenRouter key + model), then apply
/// the chosen preferences (personality, Claude model, context window) to the config store. Vestad
/// restarts the agent to apply both.
export async function setProvider(
  name: string,
  result: ProviderResult,
  personality?: string,
): Promise<void> {
  const body: Record<string, unknown> =
    result.kind === "claude"
      ? { credentials: result.credentials }
      : {
          openrouter_key: result.config.key,
          openrouter_model: result.config.model,
        };
  await apiFetch(`/agents/${encodeURIComponent(name)}/provider`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  // OpenRouter's model rides along in openrouter_model above; everything else is a config-store
  // preference applied here in one PUT.
  const config: Record<string, unknown> = {};
  if (personality) config.personality = personality;
  if (result.kind === "claude" && result.model) config.model = result.model;
  if (result.maxContextTokens != null) {
    config.max_context_tokens = result.maxContextTokens;
  }
  if (Object.keys(config).length > 0) await setConfig(name, config);
}

export interface ProviderInfo {
  state: string;
  kind: "claude" | "openrouter" | "none";
  model: string | null;
  max_context_tokens: number | null;
  setup_complete: boolean;
}

/// Read an agent's current provider (kind + model), proxied from the agent.
export async function getProvider(name: string): Promise<ProviderInfo> {
  return apiJson<ProviderInfo>(`/agents/${encodeURIComponent(name)}/provider`);
}

/// An agent's editable preferences (the config-store bucket), proxied from the agent.
export interface AgentConfig {
  model: string;
  max_context_tokens: number | null;
  personality: string;
  thinking: string;
}

/// Update an agent's editable preferences via its config store (PUT /config). Any subset of
/// model/context/personality/thinking; vestad restarts the agent so the change takes effect.
export async function setConfig(
  name: string,
  config: {
    model?: string;
    max_context_tokens?: number | null;
    personality?: string;
    thinking?: string;
  },
): Promise<void> {
  await apiFetch(`/agents/${encodeURIComponent(name)}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

/// Read an agent's current editable preferences, proxied from the agent.
export async function getConfig(name: string): Promise<AgentConfig> {
  return apiJson<AgentConfig>(`/agents/${encodeURIComponent(name)}/config`);
}

/// Change only the model preference. Vestad restarts the agent so it takes effect.
export async function setModel(name: string, model: string): Promise<void> {
  await setConfig(name, { model });
}

/// Change only the context window (tokens). Vestad restarts the agent so it takes effect.
export async function setContextWindow(
  name: string,
  maxContextTokens: number,
): Promise<void> {
  await setConfig(name, { max_context_tokens: maxContextTokens });
}

/// Create an empty agent container. Credentials and preferences (provider, model, personality,
/// context) are sent once it's up, via `setProvider`.
export async function createAgent(name: string): Promise<void> {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  await apiJson("/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, timezone }),
  });
}

/// Coarse, ordered stages of first-time agent creation reported by vestad while
/// the create POST is in flight. The image step (`pulling` on a release build,
/// `building` from a local checkout) is the dominant wait.
export type BuildPhase =
  | "pulling"
  | "building"
  | "preparing"
  | "creating"
  | "starting";

const BUILD_PHASE_MESSAGES: Record<BuildPhase, string> = {
  pulling: "downloading the agent image...",
  building: "building the agent image...",
  preparing: "preparing agent code...",
  creating: "creating the container...",
  starting: "starting up...",
};

/// Map a build phase to an honest, lowercase status line. A null phase (the
/// create has not reported yet, or has already settled) falls back to a neutral
/// line rather than a fabricated near-done claim.
export function buildPhaseMessage(phase: BuildPhase | null): string {
  return phase === null ? "setting things up..." : BUILD_PHASE_MESSAGES[phase];
}

/// Read the current in-flight build phase for an agent, or null when none is
/// recorded. Best-effort status only; the create flow owns success and failure.
export async function getBuildPhase(name: string): Promise<BuildPhase | null> {
  const resp = await apiJson<{ phase: BuildPhase | null }>(
    `/agents/${encodeURIComponent(name)}/build-phase`,
  );
  return resp.phase;
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
    if (
      resp.status === "dead" ||
      resp.status === "stopped" ||
      resp.status === "not_found"
    ) {
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
    if (
      resp.status === "dead" ||
      resp.status === "stopped" ||
      resp.status === "not_found" ||
      resp.status === "not_authenticated"
    ) {
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
