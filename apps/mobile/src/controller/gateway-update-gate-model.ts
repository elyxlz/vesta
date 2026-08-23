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
  "none" | "push-update" | "replace-update" | "dismiss";

export interface GatewayUpdateGateDecision {
  action: GatewayUpdateGateNavigationAction;
  backdropBlocked: boolean;
}

interface GatewayUpdateGateInput {
  blocked: boolean;
  // A gateway operation in flight, or its landing still showing: the sheet renders both.
  operationPresented: boolean;
  privacyBlocked: boolean;
  privacyRouteActive: boolean;
  gatewayUpdateRouteActive: boolean;
  replaceActiveRoute: boolean;
}

// One decision set from one input set: the sheet navigation and the blocking backdrop share the
// same precedence (privacy first, then whatever the sheet has to show), so the two can never
// disagree. The sheet is up for a needed update and for an operation from its start to its
// landing, morphing between them in place.
export function gatewayUpdateGateDecision(
  input: GatewayUpdateGateInput,
): GatewayUpdateGateDecision {
  const privacyOwns = input.privacyBlocked || input.privacyRouteActive;
  const presented = !privacyOwns && (input.blocked || input.operationPresented);
  return {
    action: navigationAction(input, presented),
    backdropBlocked: presented,
  };
}

function navigationAction(
  {
    privacyBlocked,
    privacyRouteActive,
    gatewayUpdateRouteActive,
    replaceActiveRoute,
  }: GatewayUpdateGateInput,
  presented: boolean,
): GatewayUpdateGateNavigationAction {
  if (privacyBlocked || privacyRouteActive) return "none";
  if (presented) {
    if (gatewayUpdateRouteActive) return "none";
    return replaceActiveRoute ? "replace-update" : "push-update";
  }
  return gatewayUpdateRouteActive ? "dismiss" : "none";
}
