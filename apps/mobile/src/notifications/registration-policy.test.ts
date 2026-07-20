import { describe, expect, it } from "vitest";
import {
  gatewayHandoffDecision,
  pushRegistrationDecision,
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
