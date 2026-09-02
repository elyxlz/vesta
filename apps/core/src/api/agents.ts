import {
  agentIsConnectable,
  agentIsDown,
  agentNeedsUser,
} from "../agent-status/agent-status";
import { restartBody, type RestartReason } from "../lifecycle/restart-reasons";
import type { AgentStatus } from "../protocol/tree";
import { jsonInit, type HttpClient } from "../transport/http";

// Every gateway route lives once, here under api/: a function taking the app's HttpClient first,
// the path spelled nowhere else. An app never builds an /agents/ or /gateway/ path itself.
export function agentPath(name: string, suffix = ""): string {
  return `/agents/${encodeURIComponent(name)}${suffix}`;
}

// Create an empty agent container. Credentials and preferences (provider, model, personality,
// context, timezone) are sent once it is up, via provisionAgent.
export async function createAgent(
  http: HttpClient,
  name: string,
): Promise<void> {
  await http.json("/agents", jsonInit("POST", { name }));
}

export async function startAgent(
  http: HttpClient,
  name: string,
): Promise<void> {
  await http.request(agentPath(name, "/start"), { method: "POST" });
}

export async function stopAgent(http: HttpClient, name: string): Promise<void> {
  await http.request(agentPath(name, "/stop"), { method: "POST" });
}

// Restart an agent. `reason` is omitted for a plain manual restart, leaving vestad to name it (it
// prefers a mount-grant delta it can derive over a generic one).
export async function restartAgent(
  http: HttpClient,
  name: string,
  reason?: RestartReason,
): Promise<void> {
  await http.request(
    agentPath(name, "/restart"),
    reason === undefined
      ? { method: "POST" }
      : jsonInit("POST", restartBody(reason)),
  );
}

export async function deleteAgent(
  http: HttpClient,
  name: string,
): Promise<void> {
  await http.request(agentPath(name), { method: "DELETE" });
}

// Rename an agent (PATCH /agents/{name}). Vestad recreates the container on the new name's network,
// carries the backup repo and settings across, and normalizes the name server-side; the normalized
// final name is returned so the caller can navigate to it.
export async function renameAgent(
  http: HttpClient,
  name: string,
  newName: string,
): Promise<string> {
  const response = await http.json<{ name: string }>(
    agentPath(name),
    jsonInit("PATCH", { new_name: newName }),
  );
  return response.name;
}

export interface AgentStatusResponse {
  status: AgentStatus;
  booting?: boolean;
}

export async function fetchAgentStatus(
  http: HttpClient,
  name: string,
): Promise<AgentStatusResponse> {
  return http.json<AgentStatusResponse>(agentPath(name));
}

export class AgentStatusError extends Error {
  readonly status: AgentStatus;

  constructor(name: string, status: AgentStatus) {
    super(`${name}: ${status}`);
    this.name = "AgentStatusError";
    this.status = status;
  }
}

interface StatusWait {
  ready: (response: AgentStatusResponse) => boolean;
  failed: (response: AgentStatusResponse) => boolean;
  timeoutLabel: string;
}

// Poll /agents/{name} until its status settles into one of `ready` (resolve) or `failed` (throw);
// anything else (still starting up) keeps polling until `timeoutMs` elapses.
async function waitForStatus(
  http: HttpClient,
  name: string,
  timeoutMs: number,
  pollIntervalMs: number,
  wait: StatusWait,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = await fetchAgentStatus(http, name);
    if (wait.ready(response)) return;
    if (wait.failed(response))
      throw new AgentStatusError(name, response.status);
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }
  throw new Error(`${name}: ${wait.timeoutLabel}`);
}

// Poll until the agent reports a settled HTTP-up status. A brand-new empty agent boots into
// "unprovisioned" (no provider chosen) until provisioned; a re-auth case reports "not_authenticated".
export async function waitUntilRunning(
  http: HttpClient,
  name: string,
  timeoutMs: number,
  pollIntervalMs = 500,
): Promise<void> {
  await waitForStatus(http, name, timeoutMs, pollIntervalMs, {
    ready: ({ status }) => agentIsConnectable(status),
    failed: ({ status }) => agentIsDown(status),
    timeoutLabel: "timed out waiting for HTTP server",
  });
}

export async function waitUntilReady(
  http: HttpClient,
  name: string,
  timeoutMs: number,
  pollIntervalMs = 500,
): Promise<void> {
  await waitForStatus(http, name, timeoutMs, pollIntervalMs, {
    ready: ({ status, booting }) => status === "alive" && booting === false,
    // A waiting agent never becomes alive on its own, so it is a failure here even though the
    // HTTP-up poll above treats it as ready.
    failed: ({ status }) => agentIsDown(status) || agentNeedsUser(status),
    timeoutLabel: "timed out waiting to become ready",
  });
}

// Normalized, provider-agnostic plan usage (the agent's GET /usage). `meters` are time-windowed
// quota gauges (Claude rate-limit buckets); `credits` is a spend balance (OpenRouter, or Claude
// extra-usage). Both already in display units (percent and dollars).
export interface UsageMeter {
  label: string;
  used_pct: number | null;
  resets_at: string | null;
}

export interface UsageCredits {
  used: number | null;
  limit: number | null;
}

// The account behind the active provider (best-effort). Providers with no identity endpoint
// report null, and any field the provider does not expose stays null.
export interface Account {
  name: string | null;
  email: string | null;
  plan: string | null;
  organization: string | null;
  created_at: string | null;
}

export interface Usage {
  meters: UsageMeter[];
  credits: UsageCredits | null;
  account: Account | null;
}

export async function fetchUsage(
  http: HttpClient,
  name: string,
): Promise<Usage> {
  return http.json<Usage>(agentPath(name, "/usage"));
}
