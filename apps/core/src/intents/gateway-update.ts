import type { HttpClient } from "../transport/http"

// A manual check fetches from GitHub server-side, so allow longer than vestad's own 10s fetch.
export const VERSION_CHECK_TIMEOUT_MS = 15000

// The one owner of the gateway self-update request. Returns whether an update actually started:
// vestad answers 200 with `started: false` when the gateway already runs the newest release, which
// leaves nothing for the caller to watch, so a spinner started on the click has to come back down.
// A started update reports its phases as gateway state on /sync; nothing here waits for it.
export async function triggerGatewayUpdate(http: HttpClient): Promise<boolean> {
  try {
    const body = await http.json<{ started?: unknown }>("/gateway/update", { method: "POST" })
    return body.started === true
  } catch {
    return false
  }
}

// Drop a failed update the user has acknowledged, which releases every app from the update screen.
// Returns whether vestad accepted it; a running update refuses (409) and keeps its screen.
export async function dismissGatewayUpdate(http: HttpClient): Promise<boolean> {
  try {
    await http.request("/gateway/update/dismiss", { method: "POST" })
    return true
  } catch {
    return false
  }
}

// The one owner of the gateway restart request. Returns whether vestad accepted it; like an update,
// the gateway drops every connection briefly and comes back, so the caller reuses the update flow's
// reconnect UX to re-attach.
export async function triggerGatewayRestart(http: HttpClient): Promise<boolean> {
  try {
    await http.request("/gateway/restart", { method: "POST" })
    return true
  } catch {
    return false
  }
}

// Ask vestad to refresh its update status. The response body is ignored on purpose: the refreshed
// updateAvailable/latestVersion arrive as a /sync gateway state delta into the replica, the single
// source both apps read. A transport failure propagates so callers can reflect it (react-query
// error state, a warning log); success simply lets the replica delta land.
export async function checkForGatewayUpdate(http: HttpClient): Promise<void> {
  await http.request("/version/check", {
    method: "POST",
    signal: AbortSignal.timeout(VERSION_CHECK_TIMEOUT_MS),
  })
}
