import { apiJson, apiFetch, jsonInit } from "./client";
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

// One match condition over a notification field. `field` is a concrete notification key (chat_name,
// chat_type, …) or an alias ("sender" = the identity fields, "text" = body/message). `op` is a
// case-insensitive substring ("contains") or regex; `negate` inverts it. Mirrors core's FieldPredicate.
export interface FieldPredicate {
  field: string;
  op: "contains" | "regex";
  value: string;
  negate?: boolean;
}

export interface NotificationInterruptRule {
  id: string;
  source?: string | null;
  type?: string | null;
  // All conditions beyond source/type (sender, keyword, and any arbitrary field) are predicates here,
  // ANDed together. Empty = the rule matches every notification of the given source/type.
  match?: FieldPredicate[];
  action: "interrupt" | "pool";
}

/// Read the agent's ordered notification interrupt ruleset from its config (GET /config).
export async function getNotificationInterruptRules(
  name: string,
): Promise<NotificationInterruptRule[]> {
  const resp = await apiJson<{
    notification_rules?: NotificationInterruptRule[];
  }>(`/agents/${encodeURIComponent(name)}/config`);
  return resp.notification_rules ?? [];
}

/// Replace the ruleset on the agent's config (PUT /config with {notification_rules}). Live — the agent
/// applies it on its next tick, no restart. Rule ids are generated client-side, so the saved rules are
/// exactly what was sent.
export async function setNotificationInterruptRules(
  name: string,
  rules: NotificationInterruptRule[],
): Promise<NotificationInterruptRule[]> {
  await apiFetch(`/agents/${encodeURIComponent(name)}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notification_rules: rules }),
  });
  return rules;
}

/// One page of received notifications, newest first (GET /history?channel=notifications). Pass the
/// returned `cursor` to fetch the next older page; a null cursor means there are no older ones.
/// Pending state isn't derived here — it's seeded from the connect snapshot and kept live via
/// `notification_cleared` deltas.
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

/// A user-granted host filesystem access: a host path bind-mounted into the agent's container at
/// `container_path` (defaults to `host_path` when unset by the caller), read-only unless `writable`.
export interface HostMount {
  host_path: string;
  container_path: string;
  writable: boolean;
}

/// Read the agent's host filesystem grants (GET /mounts).
export async function getAgentMounts(name: string): Promise<HostMount[]> {
  const resp = await apiJson<{ mounts: HostMount[] }>(
    `/agents/${encodeURIComponent(name)}/mounts`,
  );
  return resp.mounts;
}

/// Replace the agent's host filesystem grants (PUT /mounts). The server validates each grant
/// (host path exists, container path isn't protected, no duplicate container paths) and returns the
/// validated list plus whether a restart is needed to apply it (always true today).
export async function setAgentMounts(
  name: string,
  mounts: HostMount[],
): Promise<{ mounts: HostMount[]; restartRequired: boolean }> {
  const resp = await apiJson<{
    mounts: HostMount[];
    restart_required: boolean;
  }>(`/agents/${encodeURIComponent(name)}/mounts`, jsonInit("PUT", { mounts }));
  return { mounts: resp.mounts, restartRequired: resp.restart_required };
}

/// Existing host folders vestad suggests sharing (GET /host/folders), so the user doesn't
/// hand-type a path. Host-level (not agent-scoped) and API-key only.
export async function getHostFolderSuggestions(): Promise<string[]> {
  const resp = await apiJson<{ folders: string[] }>("/host/folders");
  return resp.folders;
}
