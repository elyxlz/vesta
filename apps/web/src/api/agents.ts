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

/// The nested provider body for `PUT /provider` (sign in / switch). The claude OAuth blob travels as
/// a transient `credentials` field (written to the SDK file, never stored); openrouter carries `key`.
type ProviderBody =
  | {
      kind: "claude";
      credentials: string;
      model?: string;
      max_context_tokens?: number;
    }
  | {
      kind: "openrouter";
      model: string;
      key: string;
      max_context_tokens?: number;
    };

/// Provision/attach a provider: map the chosen `ProviderResult` to the `PUT /provider` body, write any
/// prefs (personality/timezone) to `PUT /config`, then restart once to apply. Re-provisioning an
/// existing agent omits timezone/personality to keep the agent's own.
export async function setProvider(
  name: string,
  result: ProviderResult,
  personality?: string,
  timezone?: string,
): Promise<void> {
  const enc = encodeURIComponent(name);
  const body: ProviderBody =
    result.kind === "claude"
      ? {
          kind: "claude",
          credentials: result.credentials,
          ...(result.model ? { model: result.model } : {}),
          ...(result.maxContextTokens != null
            ? { max_context_tokens: result.maxContextTokens }
            : {}),
        }
      : {
          kind: "openrouter",
          model: result.config.model,
          key: result.config.key,
          ...(result.maxContextTokens != null
            ? { max_context_tokens: result.maxContextTokens }
            : {}),
        };
  await apiFetch(`/agents/${enc}/provider`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const prefs: Record<string, string> = {};
  if (personality) prefs.agent_personality = personality;
  if (timezone) prefs.timezone = timezone;
  if (Object.keys(prefs).length > 0) {
    await apiFetch(`/agents/${enc}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(prefs),
    });
  }
  await restartAgent(name);
}

/// Sign out: clear the agent's provider credentials (`DELETE /provider`), then restart so it boots
/// not_authenticated.
export async function signOutProvider(name: string): Promise<void> {
  await apiFetch(`/agents/${encodeURIComponent(name)}/provider`, {
    method: "DELETE",
  });
  await restartAgent(name);
}

export interface ProviderInfo {
  kind: "claude" | "openrouter" | "none";
  model: string | null;
  max_context_tokens: number | null;
}

/// Read an agent's active provider from its `GET /provider`. An unauthenticated agent (no creds, or
/// signed out) reports `authed: false`, which we surface as `kind: "none"` for the UI.
export async function getProvider(name: string): Promise<ProviderInfo> {
  const provider = await apiJson<{
    kind?: "claude" | "openrouter";
    model: string | null;
    max_context_tokens: number | null;
    authed?: boolean;
  }>(`/agents/${encodeURIComponent(name)}/provider`);
  return {
    kind: provider.authed ? (provider.kind ?? "none") : "none",
    model: provider.model,
    max_context_tokens: provider.max_context_tokens,
  };
}

/// Patch a provider preference (model / context) via `PATCH /provider`, then restart to apply.
async function patchProvider(
  name: string,
  patch: Record<string, unknown>,
): Promise<void> {
  await apiFetch(`/agents/${encodeURIComponent(name)}/provider`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  await restartAgent(name);
}

/// Change only the model. Vestad restarts the agent so it takes effect.
export async function setModel(name: string, model: string): Promise<void> {
  await patchProvider(name, { model });
}

/// Change only the context window. Vestad restarts the agent so it takes effect.
export async function setContextWindow(
  name: string,
  maxContextTokens: number,
): Promise<void> {
  await patchProvider(name, { max_context_tokens: maxContextTokens });
}

/// Create an empty agent container. Credentials and preferences (provider, model, personality,
/// context, timezone) are sent once it's up, via `setProvider`.
export async function createAgent(name: string): Promise<void> {
  await apiJson("/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
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
  await apiJson(`/agents/${encodeURIComponent(name)}`, {
    method: "DELETE",
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

/// Normalized, provider-agnostic plan usage (agent's GET /usage). `meters` are
/// time-windowed quota gauges (Claude rate-limit buckets); `credits` is a spend balance
/// (OpenRouter, or Claude extra-usage). Both already in display units (% and dollars).
export interface UsageMeter {
  label: string;
  used_pct: number | null;
  resets_at: string | null;
}

export interface UsageCredits {
  used: number | null;
  limit: number | null;
}

export interface Usage {
  meters: UsageMeter[];
  credits: UsageCredits | null;
}

export async function fetchUsage(name: string): Promise<Usage> {
  return apiJson(`/agents/${encodeURIComponent(name)}/usage`);
}
