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

export interface RegistrationTarget {
  gatewayUrl: string;
  token: string;
}

// A push registration is identified by the gateway it targets plus the device token; the token is
// a device-global singleton shared across gateways, so both fields are needed to tell one
// registration from another.
export function isSameRegistration(
  a: RegistrationTarget | null,
  b: RegistrationTarget | null,
): boolean {
  return (
    a !== null &&
    b !== null &&
    a.gatewayUrl === b.gatewayUrl &&
    a.token === b.token
  );
}

// Restoring the persisted snapshot on mount must never clobber a registration that already landed
// during the async restore window; a live in-memory snapshot wins over the disk one.
export function resolveHydratedSnapshot<Snapshot>(
  current: Snapshot | null,
  stored: Snapshot | null,
): Snapshot | null {
  return current ?? stored;
}
