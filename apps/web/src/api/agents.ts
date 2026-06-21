import { apiJson, apiFetch, jsonInit } from "./client";

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
  await apiFetch(
    `/agents/${encodeURIComponent(name)}/provider`,
    jsonInit("POST", body),
  );
  // OpenRouter's model rides along in openrouter_model above; everything else is a config-store
  // preference applied here in one PUT.
  const config: Record<string, unknown> = {};
  if (personality) config.agent_personality = personality;
  if (result.kind === "claude" && result.model)
    config.agent_model = result.model;
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

/// An agent's config, proxied from the agent (GET /config). Keys are VestaConfig's own field names;
/// secrets are redacted. The client picks which to show/edit. This lists the commonly-edited subset.
export interface AgentConfig {
  agent_model: string;
  max_context_tokens: number | null;
  agent_personality: string;
  thinking: string;
}

/// Update any agent config field via its config store (PUT /config), keyed by VestaConfig field name.
/// An omitted field is left unchanged, a null clears it; vestad restarts the agent to apply.
export async function setConfig(
  name: string,
  config: Record<string, unknown>,
): Promise<void> {
  await apiFetch(
    `/agents/${encodeURIComponent(name)}/config`,
    jsonInit("PUT", config),
  );
}

/// Read an agent's current config, proxied from the agent.
export async function getConfig(name: string): Promise<AgentConfig> {
  return apiJson<AgentConfig>(`/agents/${encodeURIComponent(name)}/config`);
}

/// Change only the model preference. Vestad restarts the agent so it takes effect.
export async function setModel(name: string, model: string): Promise<void> {
  await setConfig(name, { agent_model: model });
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
  await apiJson("/agents", jsonInit("POST", { name, timezone }));
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

// A status the agent can never advance past, so polling should fail fast instead of
// waiting for the deadline. `not_authenticated` is terminal for "alive" but a success
// for "running" (a fresh agent boots there), so each waiter passes its own success set.
const TERMINAL_STATUSES = ["dead", "stopped", "not_found", "not_authenticated"];

async function waitForStatus(
  name: string,
  timeoutMs: number,
  successStatuses: string[],
  timedOutMessage: string,
  pollIntervalMs = 500,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const resp = await apiJson<{ status: string }>(
      `/agents/${encodeURIComponent(name)}`,
    );
    if (successStatuses.includes(resp.status)) return;
    if (TERMINAL_STATUSES.includes(resp.status)) {
      throw new Error(`${name}: ${resp.status}`);
    }
    await new Promise((r) => setTimeout(r, pollIntervalMs));
  }
  throw new Error(`${name}: ${timedOutMessage}`);
}

/// Poll /agents/{name} until it reports "alive" or "not_authenticated".
/// A brand-new empty agent boots into not_authenticated until provisioned.
export function waitUntilRunning(
  name: string,
  timeoutMs: number,
  pollIntervalMs = 500,
): Promise<void> {
  return waitForStatus(
    name,
    timeoutMs,
    ["alive", "not_authenticated"],
    "timed out waiting for HTTP server",
    pollIntervalMs,
  );
}

export function waitUntilAlive(
  name: string,
  timeoutMs: number,
  pollIntervalMs = 500,
): Promise<void> {
  return waitForStatus(
    name,
    timeoutMs,
    ["alive"],
    "timed out waiting to become alive",
    pollIntervalMs,
  );
}

async function agentAction(name: string, action: string): Promise<void> {
  await apiJson(`/agents/${encodeURIComponent(name)}/${action}`, {
    method: "POST",
  });
}

export function startAgent(name: string): Promise<void> {
  return agentAction(name, "start");
}

export function stopAgent(name: string): Promise<void> {
  return agentAction(name, "stop");
}

export function restartAgent(name: string): Promise<void> {
  return agentAction(name, "restart");
}

export function deleteAgent(name: string): Promise<void> {
  return agentAction(name, "destroy");
}

export function rebuildAgent(name: string): Promise<void> {
  return agentAction(name, "rebuild");
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
