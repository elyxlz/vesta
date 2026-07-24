import { describe, expect, it } from "vitest";
import {
  gatewayHandoffDecision,
  isSameRegistration,
  pushRegistrationDecision,
  resolveHydratedSnapshot,
} from "./registration-policy";

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

describe("gateway handoff", () => {
  const cases: {
    name: string;
    previousGatewayUrl: string | null;
    currentGatewayUrl: string | null;
    sessionStatus: "booting" | "disconnected" | "connected";
    expected: "keep" | "unregister-previous";
  }[] = [
    {
      name: "keeps the registration when the gateway is unchanged",
      previousGatewayUrl: "https://a.test",
      currentGatewayUrl: "https://a.test",
      sessionStatus: "connected",
      expected: "keep",
    },
    {
      name: "unregisters the previous gateway after a switch",
      previousGatewayUrl: "https://a.test",
      currentGatewayUrl: "https://b.test",
      sessionStatus: "connected",
      expected: "unregister-previous",
    },
    {
      name: "unregisters the previous gateway on disconnect",
      previousGatewayUrl: "https://a.test",
      currentGatewayUrl: null,
      sessionStatus: "disconnected",
      expected: "unregister-previous",
    },
    {
      name: "keeps when there is no previous registration",
      previousGatewayUrl: null,
      currentGatewayUrl: "https://a.test",
      sessionStatus: "connected",
      expected: "keep",
    },
    {
      name: "waits while booting so a cold start never tears down its own registration",
      previousGatewayUrl: "https://a.test",
      currentGatewayUrl: "https://b.test",
      sessionStatus: "booting",
      expected: "keep",
    },
  ];

  it.each(cases)(
    "$name",
    ({ previousGatewayUrl, currentGatewayUrl, sessionStatus, expected }) => {
      expect(
        gatewayHandoffDecision({
          previousGatewayUrl,
          currentGatewayUrl,
          sessionStatus,
        }),
      ).toBe(expected);
    },
  );
});

describe("registration identity", () => {
  const target = { gatewayUrl: "https://a.test", token: "tok-1" };

  it("matches an identical gateway and token", () => {
    expect(isSameRegistration(target, { ...target })).toBe(true);
  });

  it("differs when the token was replaced by a newer registration", () => {
    expect(
      isSameRegistration(target, { gatewayUrl: "https://a.test", token: "tok-2" }),
    ).toBe(false);
  });

  it("differs when the gateway differs", () => {
    expect(
      isSameRegistration(target, { gatewayUrl: "https://b.test", token: "tok-1" }),
    ).toBe(false);
  });

  it("never matches when either side is absent", () => {
    expect(isSameRegistration(null, target)).toBe(false);
    expect(isSameRegistration(target, null)).toBe(false);
    expect(isSameRegistration(null, null)).toBe(false);
  });
});

describe("snapshot hydration merge", () => {
  const live = { id: "live" };
  const stored = { id: "stored" };

  it("keeps a registration that landed during the restore window", () => {
    expect(resolveHydratedSnapshot(live, stored)).toBe(live);
  });

  it("adopts the persisted snapshot when the ref is still empty", () => {
    expect(resolveHydratedSnapshot(null, stored)).toBe(stored);
  });

  it("stays empty when neither exists", () => {
    expect(resolveHydratedSnapshot(null, null)).toBeNull();
  });
});
