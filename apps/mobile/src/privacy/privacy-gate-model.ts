export type PrivacyGateNavigationAction =
  | "none"
  | "push-privacy"
  | "replace-privacy"
  | "back"
  | "dismiss-to-connect"
  | "replace-root";

interface PrivacyGateNavigationInput {
  blocked: boolean;
  presentationReady: boolean;
  privacyRouteActive: boolean;
  replaceActiveRoute: boolean;
  sessionStatus: "booting" | "disconnected" | "connected";
  canGoBack: boolean;
}

export function privacyGateNavigationAction({
  blocked,
  presentationReady,
  privacyRouteActive,
  replaceActiveRoute,
  sessionStatus,
  canGoBack,
}: PrivacyGateNavigationInput): PrivacyGateNavigationAction {
  if (!presentationReady) return "none";

  if (blocked) {
    if (privacyRouteActive) return "none";
    return replaceActiveRoute ? "replace-privacy" : "push-privacy";
  }

  if (!privacyRouteActive) return "none";
  if (sessionStatus === "booting") return "none";
  if (sessionStatus === "disconnected") return "dismiss-to-connect";
  return canGoBack ? "back" : "replace-root";
}

interface AutomaticUnlockInput {
  presentationReady: boolean;
  privacyRouteActive: boolean;
  hydrated: boolean;
  locked: boolean;
  authenticating: boolean;
  initializationFailed: boolean;
  attempted: boolean;
}

export function shouldAutomaticallyUnlock({
  presentationReady,
  privacyRouteActive,
  hydrated,
  locked,
  authenticating,
  initializationFailed,
  attempted,
}: AutomaticUnlockInput): boolean {
  return (
    presentationReady &&
    privacyRouteActive &&
    hydrated &&
    locked &&
    !authenticating &&
    !initializationFailed &&
    !attempted
  );
}
