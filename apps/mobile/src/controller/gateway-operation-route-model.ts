export type GatewayOperationRouteAction = "none" | "home";

// The routes a running gateway operation leaves reachable, by their first path segment. Home
// (the undefined segment) renders the operation itself and settings is where a user goes when an
// update looks stuck, the same policy web's NavigationGuard applies. Privacy and the gateway-update
// sheet are listed because another gate owns navigation while either is up: sending the app home
// under one of them would fight the gate that put it there.
const REACHABLE_DURING_OPERATION = new Set([
  "settings",
  "privacy",
  "gateway-update",
]);

// Where the app must be while an operation runs: agent pages are unavailable (their agent may be
// mid-backup and the gateway is about to restart), so anything else goes home.
export function gatewayOperationRouteAction({
  operating,
  activeRoute,
}: {
  operating: boolean;
  activeRoute: string | undefined;
}): GatewayOperationRouteAction {
  if (!operating || activeRoute === undefined) return "none";
  return REACHABLE_DURING_OPERATION.has(activeRoute) ? "none" : "home";
}
