import {
  normalizeProviderInfo,
  providerPutBody,
  type NotificationEvent,
  type ProviderInfo,
  type ProviderSelection,
  type VestaEvent,
} from "@vesta/core";
import type { ApiClient } from "./client";
import type {
  BackupInfo,
  FileReadResponse,
  FileTreeEntry,
  GatewayInfo,
  GatewaySettings,
  HostMount,
  Manifest,
  NotificationInterruptRule,
  Usage,
  VoiceStatus,
} from "./types";

export type { ProviderSelection };

export interface OpenRouterModelOption {
  slug: string;
  label: string;
  author: string;
  note?: string;
  context_length?: number;
  input_price?: number | null;
  output_price?: number | null;
  cache_read_price?: number | null;
}

export async function fetchManifest(api: ApiClient): Promise<Manifest> {
  return api.json("/manifest");
}

export async function createAgent(api: ApiClient, name: string): Promise<void> {
  await api.request("/agents", api.jsonInit("POST", { name }));
}

export async function waitUntilRunning(
  api: ApiClient,
  name: string,
  timeoutMs = 10 * 60 * 1000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = await api.json<{ status: string }>(
      `/agents/${encodeURIComponent(name)}`,
    );
    if (
      response.status === "alive" ||
      response.status === "not_authenticated" ||
      response.status === "unprovisioned"
    ) {
      return;
    }
    if (
      response.status === "dead" ||
      response.status === "stopped" ||
      response.status === "not_found"
    ) {
      throw new Error(`${name} could not start: ${response.status}.`);
    }
    await new Promise((resolve) => setTimeout(resolve, 750));
  }
  throw new Error(`${name} did not finish starting in time.`);
}

export async function provisionAgent(
  api: ApiClient,
  name: string,
  provider: ProviderSelection,
  personality?: string,
  timezone?: string,
): Promise<void> {
  const providerBody = providerPutBody(provider);
  const encoded = encodeURIComponent(name);
  await api.request(
    `/agents/${encoded}/provider`,
    api.jsonInit("PUT", providerBody),
  );
  if (personality || timezone) {
    await api.request(
      `/agents/${encoded}/config`,
      api.jsonInit("PUT", {
        ...(personality ? { agent_personality: personality } : {}),
        ...(timezone ? { timezone } : {}),
      }),
    );
  }
  await restartAgent(api, name);
}

export async function startClaudeOAuth(
  api: ApiClient,
): Promise<{ auth_url: string; session_id: string }> {
  return api.json("/providers/claude/oauth/start", { method: "POST" });
}

export async function completeClaudeOAuth(
  api: ApiClient,
  sessionId: string,
  code: string,
): Promise<string> {
  const result = await api.json<{ credentials: string }>(
    "/providers/claude/oauth/complete",
    api.jsonInit("POST", { session_id: sessionId, code }),
  );
  return result.credentials;
}

export async function startOpenAIOAuth(
  api: ApiClient,
): Promise<{ auth_url: string; user_code: string; session_id: string }> {
  return api.json("/providers/openai/oauth/start", { method: "POST" });
}

export async function completeOpenAIOAuth(
  api: ApiClient,
  sessionId: string,
): Promise<string> {
  const result = await api.json<{ credentials: string }>(
    "/providers/openai/oauth/complete",
    api.jsonInit("POST", { session_id: sessionId }),
  );
  return result.credentials;
}

export async function fetchOpenRouterModels(
  api: ApiClient,
): Promise<OpenRouterModelOption[]> {
  return api.json("/providers/openrouter/models/top");
}

export async function validateOpenRouterKey(
  api: ApiClient,
  key: string,
): Promise<void> {
  await api.request(
    "/providers/openrouter/validate-key",
    api.jsonInit("POST", { key }),
  );
}

export async function getProvider(
  api: ApiClient,
  name: string,
): Promise<ProviderInfo> {
  return normalizeProviderInfo(
    await api.json(`/agents/${encodeURIComponent(name)}/provider`),
  );
}

async function patchProvider(
  api: ApiClient,
  name: string,
  patch: Record<string, unknown>,
): Promise<void> {
  await api.request(
    `/agents/${encodeURIComponent(name)}/provider`,
    api.jsonInit("PATCH", patch),
  );
  await restartAgent(api, name);
}

export async function setModel(
  api: ApiClient,
  name: string,
  model: string,
): Promise<void> {
  await patchProvider(api, name, { model });
}

export async function setContextWindow(
  api: ApiClient,
  name: string,
  maxContextTokens: number,
): Promise<void> {
  await patchProvider(api, name, {
    max_context_tokens: maxContextTokens,
  });
}

export async function signOutProvider(
  api: ApiClient,
  name: string,
): Promise<void> {
  await api.request(`/agents/${encodeURIComponent(name)}/provider`, {
    method: "DELETE",
  });
  await restartAgent(api, name);
}

export async function startAgent(api: ApiClient, name: string): Promise<void> {
  await api.request(`/agents/${encodeURIComponent(name)}/start`, {
    method: "POST",
  });
}

export async function stopAgent(api: ApiClient, name: string): Promise<void> {
  await api.request(`/agents/${encodeURIComponent(name)}/stop`, {
    method: "POST",
  });
}

export async function restartAgent(
  api: ApiClient,
  name: string,
): Promise<void> {
  await api.request(`/agents/${encodeURIComponent(name)}/restart`, {
    method: "POST",
  });
}

export async function deleteAgent(api: ApiClient, name: string): Promise<void> {
  await api.request(`/agents/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export async function createBackup(
  api: ApiClient,
  name: string,
): Promise<BackupInfo> {
  return api.json(`/agents/${encodeURIComponent(name)}/backups`, {
    method: "POST",
  });
}

export async function listBackups(
  api: ApiClient,
  name: string,
): Promise<BackupInfo[]> {
  return api.json(`/agents/${encodeURIComponent(name)}/backups`);
}

export async function restoreBackup(
  api: ApiClient,
  name: string,
  backupId: string,
): Promise<void> {
  await api.request(
    `/agents/${encodeURIComponent(name)}/backups/${encodeURIComponent(backupId)}/restore`,
    { method: "POST" },
  );
}

export async function deleteBackup(
  api: ApiClient,
  name: string,
  backupId: string,
): Promise<void> {
  await api.request(
    `/agents/${encodeURIComponent(name)}/backups/${encodeURIComponent(backupId)}`,
    { method: "DELETE" },
  );
}

export async function fetchUsage(api: ApiClient, name: string): Promise<Usage> {
  return api.json(`/agents/${encodeURIComponent(name)}/usage`);
}

export async function getNotificationHistory(
  api: ApiClient,
  name: string,
  cursor?: number,
): Promise<{ notifications: NotificationEvent[]; cursor: number | null }> {
  const parameters = new URLSearchParams({ channel: "notifications" });
  if (cursor !== undefined) parameters.set("cursor", String(cursor));
  const response = await api.json<{
    events: VestaEvent[];
    cursor: number | null;
  }>(`/agents/${encodeURIComponent(name)}/history?${parameters.toString()}`);
  const notifications = response.events.filter(
    (event): event is NotificationEvent => event.type === "notification",
  );
  notifications.reverse();
  return { notifications, cursor: response.cursor };
}

export async function getNotificationRules(
  api: ApiClient,
  name: string,
): Promise<NotificationInterruptRule[]> {
  const response = await api.json<{
    notification_rules?: NotificationInterruptRule[];
  }>(`/agents/${encodeURIComponent(name)}/config`);
  return response.notification_rules ?? [];
}

export async function setNotificationRules(
  api: ApiClient,
  name: string,
  rules: NotificationInterruptRule[],
): Promise<void> {
  await api.request(
    `/agents/${encodeURIComponent(name)}/config`,
    api.jsonInit("PUT", { notification_rules: rules }),
  );
}

export async function fetchFileTree(
  api: ApiClient,
  name: string,
): Promise<FileTreeEntry[]> {
  const response = await api.json<{
    tree: string[];
    entries?: FileTreeEntry[];
  }>(`/agents/${encodeURIComponent(name)}/tree`);
  return (
    response.entries ??
    response.tree.map((path) => ({ path, is_dir: false, mode: 0o644 }))
  );
}

export async function readFile(
  api: ApiClient,
  name: string,
  path: string,
): Promise<FileReadResponse> {
  const query = new URLSearchParams({ path });
  return api.json(
    `/agents/${encodeURIComponent(name)}/file?${query.toString()}`,
  );
}

export async function writeFile(
  api: ApiClient,
  name: string,
  path: string,
  content: string,
): Promise<void> {
  await api.request(
    `/agents/${encodeURIComponent(name)}/file`,
    api.jsonInit("PUT", { path, content }),
  );
}

export async function getAgentMounts(
  api: ApiClient,
  name: string,
): Promise<HostMount[]> {
  const response = await api.json<{ mounts: HostMount[] }>(
    `/agents/${encodeURIComponent(name)}/mounts`,
  );
  return response.mounts;
}

export async function setAgentMounts(
  api: ApiClient,
  name: string,
  mounts: HostMount[],
): Promise<{ mounts: HostMount[]; restartRequired: boolean }> {
  const response = await api.json<{
    mounts: HostMount[];
    restart_required: boolean;
  }>(
    `/agents/${encodeURIComponent(name)}/mounts`,
    api.jsonInit("PUT", { mounts }),
  );
  return {
    mounts: response.mounts,
    restartRequired: response.restart_required,
  };
}

export async function getHostFolderSuggestions(
  api: ApiClient,
): Promise<string[]> {
  const response = await api.json<{ folders: string[] }>("/host/folders");
  return response.folders;
}

export async function fetchVoiceStatus(
  api: ApiClient,
  name: string,
  domain: "stt" | "tts",
): Promise<VoiceStatus> {
  return api.json(`/agents/${encodeURIComponent(name)}/voice/${domain}/status`);
}

export async function setVoiceEnabled(
  api: ApiClient,
  name: string,
  domain: "stt" | "tts",
  value: boolean,
): Promise<void> {
  await api.request(
    `/agents/${encodeURIComponent(name)}/voice/${domain}/set-enabled`,
    api.jsonInit("POST", { value }),
  );
}

export async function setVoiceSetting(
  api: ApiClient,
  name: string,
  domain: "stt" | "tts",
  key: string,
  value: unknown,
): Promise<void> {
  await api.request(
    `/agents/${encodeURIComponent(name)}/voice/${domain}/set`,
    api.jsonInit("POST", { key, value }),
  );
}

export async function prepareSpeech(
  api: ApiClient,
  name: string,
  text: string,
): Promise<string> {
  const response = await api.json<{ id: string }>(
    `/agents/${encodeURIComponent(name)}/voice/tts/prepare`,
    api.jsonInit("POST", { text }),
  );
  return response.id;
}

export async function fetchGatewayInfo(api: ApiClient): Promise<GatewayInfo> {
  return api.json("/gateway/info");
}

export async function fetchGatewaySettings(
  api: ApiClient,
): Promise<GatewaySettings> {
  return api.json("/gateway/settings");
}

export async function registerMobileDevice(
  api: ApiClient,
  input: {
    installationId: string;
    token: string;
    platform: "ios" | "android";
    gateway: string;
    eventTypes: string[];
    previews: boolean;
  },
): Promise<void> {
  await api.request(
    "/mobile/devices",
    api.jsonInit("PUT", {
      installation_id: input.installationId,
      token: input.token,
      platform: input.platform,
      gateway: input.gateway,
      event_types: input.eventTypes,
      previews: input.previews,
    }),
  );
}

export async function unregisterMobileDevice(
  api: ApiClient,
  token: string,
): Promise<void> {
  await api.request("/mobile/devices", api.jsonInit("DELETE", { token }));
}
