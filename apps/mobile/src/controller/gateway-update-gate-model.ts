import type { SyncState } from "@vesta/core";

export interface GatewayBehindLatch {
  key: string | null;
  behind: boolean;
}

// Behind-ness is latched across the reconnect gap: every socket close drops syncState to
// "reconnecting" and only an accepted hello reaches "open", so the update sheet neither pops
// out on a transient blip nor flashes home mid-update. A changed key (a gateway switch)
// starts unlatched.
export function latchedGatewayBehind(
  latch: GatewayBehindLatch,
  connectionKey: string | null,
  syncState: SyncState,
): boolean {
  if (syncState === "gateway_behind") return true;
  return latch.key === connectionKey && syncState !== "open" && latch.behind;
}

export type GatewayUpdateGateNavigationAction =
  | "none"
  | "push-update"
  | "replace-update"
  | "dismiss"
  | "dismiss-home";

export interface GatewayUpdateGateDecision {
  action: GatewayUpdateGateNavigationAction;
  backdropBlocked: boolean;
}

interface GatewayUpdateGateInput {
  blocked: boolean;
  operationRunning: boolean;
  privacyBlocked: boolean;
  privacyRouteActive: boolean;
  gatewayUpdateRouteActive: boolean;
  replaceActiveRoute: boolean;
}

// One decision set from one input set: the sheet navigation and the blocking backdrop share the
// same precedence (privacy first, then a running operation whose progress page owns the screen),
// so the two can never disagree.
export function gatewayUpdateGateDecision(
  input: GatewayUpdateGateInput,
): GatewayUpdateGateDecision {
  return {
    action: navigationAction(input),
    backdropBlocked:
      input.blocked &&
      !input.privacyBlocked &&
      !input.privacyRouteActive &&
      !input.operationRunning,
  };
}

function navigationAction({
  blocked,
  operationRunning,
  privacyBlocked,
  privacyRouteActive,
  gatewayUpdateRouteActive,
  replaceActiveRoute,
}: GatewayUpdateGateInput): GatewayUpdateGateNavigationAction {
  if (privacyBlocked || privacyRouteActive) return "none";

  // A started update owns the flow: home renders its live progress, so the sheet hands off to it
  // seconds after the tap (dismissing straight home, never through a stale agent page) and stays
  // away for as long as the operation runs.
  if (operationRunning) {
    return gatewayUpdateRouteActive ? "dismiss-home" : "none";
  }

  if (blocked) {
    if (gatewayUpdateRouteActive) return "none";
    return replaceActiveRoute ? "replace-update" : "push-update";
  }

  return gatewayUpdateRouteActive ? "dismiss" : "none";
}
