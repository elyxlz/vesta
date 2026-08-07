export type GatewayUpdateGateNavigationAction =
  | "none"
  | "push-update"
  | "replace-update"
  | "dismiss";

interface GatewayUpdateGateNavigationInput {
  blocked: boolean;
  privacyBlocked: boolean;
  privacyRouteActive: boolean;
  gatewayUpdateRouteActive: boolean;
  replaceActiveRoute: boolean;
}

export function gatewayUpdateGateNavigationAction({
  blocked,
  privacyBlocked,
  privacyRouteActive,
  gatewayUpdateRouteActive,
  replaceActiveRoute,
}: GatewayUpdateGateNavigationInput): GatewayUpdateGateNavigationAction {
  if (privacyBlocked || privacyRouteActive) return "none";

  if (blocked) {
    if (gatewayUpdateRouteActive) return "none";
    return replaceActiveRoute ? "replace-update" : "push-update";
  }

  return gatewayUpdateRouteActive ? "dismiss" : "none";
}
