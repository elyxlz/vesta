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
