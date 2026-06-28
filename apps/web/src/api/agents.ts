import { apiJson, apiFetch } from "./client";
import type { VestaEvent } from "@/lib/types";

export type NotificationEvent = Extract<VestaEvent, { type: "notification" }>;

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
  /// "none" means no provider chosen (fresh agent, or signed out). A concrete kind with
  /// `authed: false` means a provider IS chosen but its credential is invalid/expired (re-auth).
  kind: "claude" | "openrouter" | "none";
  model: string | null;
  max_context_tokens: number | null;
  authed: boolean;
}

/// Read an agent's active provider from its `GET /provider`. The agent reports `kind` only when a
/// provider is chosen (omitted when unprovisioned) plus an `authed` flag — so the UI can tell
/// "no provider yet" (kind "none") apart from "chosen but credential expired" (kind set, authed false).
export async function getProvider(name: string): Promise<ProviderInfo> {
  const provider = await apiJson<{
    kind?: "claude" | "openrouter";
    model: string | null;
    max_context_tokens: number | null;
    authed?: boolean;
  }>(`/agents/${encodeURIComponent(name)}/provider`);
  return {
    kind: provider.kind ?? "none",
    model: provider.model,
    max_context_tokens: provider.max_context_tokens,
    authed: provider.authed ?? false,
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

/// Poll /agents/{name} until it reports a settled HTTP-up status. A brand-new empty agent boots into
/// "unprovisioned" (no provider chosen) until provisioned; a re-auth case reports "not_authenticated".
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
    if (
      resp.status === "alive" ||
      resp.status === "not_authenticated" ||
      resp.status === "unprovisioned"
    )
      return;
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
      resp.status === "not_authenticated" ||
      resp.status === "unprovisioned"
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

export interface NotificationInterruptRule {
  id: string;
  source?: string | null;
  type?: string | null;
  sender?: string | null;
  keyword?: string | null;
  action: "interrupt" | "pool";
}

/// Read the agent's ordered notification interrupt ruleset from the policy (GET /config/notification-policy).
export async function getNotificationInterruptRules(
  name: string,
): Promise<NotificationInterruptRule[]> {
  const resp = await apiJson<{ rules: NotificationInterruptRule[] }>(
    `/agents/${encodeURIComponent(name)}/config/notification-policy`,
  );
  return resp.rules;
}

/// Replace the ruleset section of the policy (PUT /config/notification-policy with {rules}; the defaults
/// section is left untouched). Live — the agent applies it on its next tick, no restart. Returns the
/// saved rules (ids assigned).
export async function setNotificationInterruptRules(
  name: string,
  rules: NotificationInterruptRule[],
): Promise<NotificationInterruptRule[]> {
  const resp = await apiJson<{ rules: NotificationInterruptRule[] }>(
    `/agents/${encodeURIComponent(name)}/config/notification-policy`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rules }),
    },
  );
  return resp.rules;
}

/// One page of received notifications, newest first (GET /history?channel=notifications). Pass the
/// returned `cursor` to fetch the next older page; a null cursor means there are no older ones.
export async function getNotificationHistory(
  name: string,
  cursor?: number,
): Promise<{ notifications: NotificationEvent[]; cursor: number | null }> {
  const params = new URLSearchParams({ channel: "notifications" });
  if (cursor != null) params.set("cursor", String(cursor));
  const resp = await apiJson<{ events: VestaEvent[]; cursor: number | null }>(
    `/agents/${encodeURIComponent(name)}/history?${params.toString()}`,
  );
  const items = resp.events.filter(
    (event): event is NotificationEvent => event.type === "notification",
  );
  // Newest-first for the view; the history endpoint returns ascending within a page.
  items.reverse();
  return { notifications: items, cursor: resp.cursor };
}

/// The ids (file stems) of notifications still on disk — received but not yet processed by the
/// agent. A notification not in this set has been cleared (its file was deleted after processing).
export async function getPendingNotifications(name: string): Promise<string[]> {
  const resp = await apiJson<{ pending: string[] }>(
    `/agents/${encodeURIComponent(name)}/notifications/pending`,
  );
  return resp.pending;
}

/// The static interrupt fallback per source/type, aggregated server-side over the whole history in
/// one query (GET /notifications/static-defaults) — the default applied when no rule matches.
export interface NotificationStaticDefault {
  source: string;
  type: string;
  interrupt: boolean;
}

export async function getNotificationStaticDefaults(
  name: string,
): Promise<NotificationStaticDefault[]> {
  const resp = await apiJson<{ defaults: NotificationStaticDefault[] }>(
    `/agents/${encodeURIComponent(name)}/notifications/static-defaults`,
  );
  return resp.defaults;
}

/// A user override of a source's static default, keyed by exact (source, type). Consulted after the
/// rules and before the source's static flag. Lives in the `defaults` section of the policy
/// (GET/PUT /config/notification-policy).
export interface NotificationDefaultOverride {
  source: string;
  type: string;
  action: "interrupt" | "pool";
}

export async function getNotificationDefaultOverrides(
  name: string,
): Promise<NotificationDefaultOverride[]> {
  const resp = await apiJson<{ defaults: NotificationDefaultOverride[] }>(
    `/agents/${encodeURIComponent(name)}/config/notification-policy`,
  );
  return resp.defaults;
}

/// Replace the defaults section of the policy (PUT /config/notification-policy with {defaults}; the rules
/// section is left untouched). Live — applied on the agent's next tick, no restart.
export async function setNotificationDefaultOverrides(
  name: string,
  defaults: NotificationDefaultOverride[],
): Promise<NotificationDefaultOverride[]> {
  const resp = await apiJson<{ defaults: NotificationDefaultOverride[] }>(
    `/agents/${encodeURIComponent(name)}/config/notification-policy`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ defaults }),
    },
  );
  return resp.defaults;
}
