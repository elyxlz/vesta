import { describe, expect, it } from "vitest";
import { pushRegistrationDecision } from "./registration-policy";

describe("push registration readiness", () => {
  it("waits for persisted preferences before doing anything", () => {
    expect(
      pushRegistrationDecision({
        preferencesHydrated: false,
        sessionStatus: "connected",
        notificationsEnabled: true,
      }),
    ).toBe("wait");
  });

  it("unregisters only after a disabled preference has hydrated", () => {
    expect(
      pushRegistrationDecision({
        preferencesHydrated: true,
        sessionStatus: "connected",
        notificationsEnabled: false,
      }),
    ).toBe("unregister");
  });

  it("registers only for a connected session with notifications enabled", () => {
    expect(
      pushRegistrationDecision({
        preferencesHydrated: true,
        sessionStatus: "connected",
        notificationsEnabled: true,
      }),
    ).toBe("register");
  });
});
