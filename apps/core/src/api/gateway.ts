import type { ReleaseChannel } from "../protocol/tree";
import { ApiError, jsonInit, type HttpClient } from "../transport/http";

// Read-only daemon reachability facts (GET /gateway/info). Distinct from the replica's GatewayInfo
// branch, which carries the live gateway state; this is the connect-time answer a settings page
// shows.
export interface GatewayEndpointInfo {
  lan: { exposed: boolean; url: string | null };
  tunnel_url: string | null;
  port: number;
}

interface GatewayRetention {
  periodic: number;
  pre_update_versions: number;
}

interface GatewayAutoBackup {
  enabled: boolean;
  every_n_days: number;
  retention: GatewayRetention;
}

export interface GatewaySettings {
  auto_update: boolean;
  channel: ReleaseChannel;
  auto_backup: GatewayAutoBackup;
}

export async function fetchGatewayInfo(
  http: HttpClient,
): Promise<GatewayEndpointInfo> {
  return http.json<GatewayEndpointInfo>("/gateway/info");
}

export async function fetchGatewaySettings(
  http: HttpClient,
): Promise<GatewaySettings> {
  return http.json<GatewaySettings>("/gateway/settings");
}

export async function updateGatewaySettings(
  http: HttpClient,
  patch: Partial<Pick<GatewaySettings, "auto_update" | "channel">>,
): Promise<GatewaySettings> {
  return http.json<GatewaySettings>(
    "/gateway/settings",
    jsonInit("PUT", patch),
  );
}

// A manual check fetches from GitHub server-side, so allow longer than vestad's own 10s fetch.
export const VERSION_CHECK_TIMEOUT_MS = 15000;

// How the gateway answered an update request. "started": vestad accepted it and reports its phases
// as gateway state on /sync, nothing here waits for it. "current": the gateway already runs the
// newest release, so there is nothing to watch. "busy": an update or restart is already in flight
// (409). "unreachable": the request never got an answer, or the gateway refused it.
export type GatewayUpdateOutcome =
  | { kind: "started" }
  | { kind: "current" }
  | { kind: "busy"; detail: string }
  | { kind: "unreachable"; detail: string };

// The one owner of the gateway self-update request.
export async function triggerGatewayUpdate(
  http: HttpClient,
): Promise<GatewayUpdateOutcome> {
  try {
    const body = await http.json<{ started?: unknown; ok?: unknown }>(
      "/gateway/update",
      { method: "POST" },
    );
    // LEGACY(remove-when: no gateway older than v0.1.190 remains): a pre-0.1.190 gateway answers
    // {ok: true} after applying the update synchronously, and this call is how the
    // gateway-behind screens update exactly such a gateway.
    if (body.started === true || body.ok === true) return { kind: "started" };
    return { kind: "current" };
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    if (error instanceof ApiError && error.status === 409)
      return { kind: "busy", detail };
    return { kind: "unreachable", detail };
  }
}

// Drop a failed update the user has acknowledged, which releases every app from the update screen.
// Returns whether vestad accepted it; a running update refuses (409) and keeps its screen.
export async function dismissGatewayUpdate(http: HttpClient): Promise<boolean> {
  try {
    await http.request("/gateway/update/dismiss", { method: "POST" });
    return true;
  } catch {
    return false;
  }
}

// The one owner of the gateway restart request. Returns whether vestad accepted it; like an update,
// the gateway drops every connection briefly and comes back, so the caller reuses the update flow's
// reconnect UX to re-attach.
export async function triggerGatewayRestart(
  http: HttpClient,
): Promise<boolean> {
  try {
    await http.request("/gateway/restart", { method: "POST" });
    return true;
  } catch {
    return false;
  }
}

// Ask vestad to refresh its update status. The response body is ignored on purpose: the refreshed
// updateAvailable/latestVersion arrive as a /sync gateway state delta into the replica, the single
// source both apps read. A transport failure propagates so callers can reflect it.
export async function checkForGatewayUpdate(http: HttpClient): Promise<void> {
  await http.request("/version/check", {
    method: "POST",
    signal: AbortSignal.timeout(VERSION_CHECK_TIMEOUT_MS),
  });
}
