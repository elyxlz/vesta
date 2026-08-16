export type GatewayUpdateGateNavigationAction =
  | "none"
  | "push-update"
  | "replace-update"
  | "dismiss"
  | "dismiss-home";

interface GatewayUpdateGateNavigationInput {
  blocked: boolean;
  operationRunning: boolean;
  privacyBlocked: boolean;
  privacyRouteActive: boolean;
  gatewayUpdateRouteActive: boolean;
  replaceActiveRoute: boolean;
}

export function gatewayUpdateGateNavigationAction({
  blocked,
  operationRunning,
  privacyBlocked,
  privacyRouteActive,
  gatewayUpdateRouteActive,
  replaceActiveRoute,
}: GatewayUpdateGateNavigationInput): GatewayUpdateGateNavigationAction {
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
