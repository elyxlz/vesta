export type PushRegistrationDecision = "wait" | "register" | "unregister";

export function pushRegistrationDecision(input: {
  preferencesHydrated: boolean;
  sessionStatus: "booting" | "disconnected" | "connected";
  notificationsEnabled: boolean;
}): PushRegistrationDecision {
  if (!input.preferencesHydrated || input.sessionStatus !== "connected") {
    return "wait";
  }
  return input.notificationsEnabled ? "register" : "unregister";
}

export type GatewayHandoffDecision = "keep" | "unregister-previous";

// Push registration lives and dies with the gateway it was made against: once the app has
// registered with gateway A, moving to a different gateway (or disconnecting) must remove that
// registration at A, or A keeps pushing forever. This decides only the previous-gateway teardown;
// the current-gateway (re)registration is pushRegistrationDecision's job.
export function gatewayHandoffDecision(input: {
  previousGatewayUrl: string | null;
  currentGatewayUrl: string | null;
  sessionStatus: "booting" | "disconnected" | "connected";
}): GatewayHandoffDecision {
  if (input.sessionStatus === "booting") return "keep";
  if (!input.previousGatewayUrl) return "keep";
  if (input.previousGatewayUrl === input.currentGatewayUrl) return "keep";
  return "unregister-previous";
}
