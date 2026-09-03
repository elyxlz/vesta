import { describe, expect, it } from "vitest";
import type { UserNotificationDelta } from "@vesta/core";
import { shouldPresentUserNotification } from "./user-notification-presentation";

function chatUserNotification(agent: string): UserNotificationDelta {
  return {
    type: "user_notification",
    id: 1,
    at: 1_700_000_000,
    agent,
    kind: "message",
    title: agent,
    body: "hi",
  };
}

function rateLimitedUserNotification(agent: string): UserNotificationDelta {
  return {
    type: "user_notification",
    id: 1,
    at: 1_700_000_000,
    agent,
    kind: "rate_limited",
    title: agent,
    body: "throttled",
  };
}

function needsUserNotification(agent: string): UserNotificationDelta {
  return {
    type: "user_notification",
    id: 1,
    at: 1_700_000_000,
    agent,
    kind: "needs_user",
    title: `${agent} needs to be set up`,
    body: "Choose a provider and sign in.",
  };
}

// The gateway's own announcement names no agent, so it can never be the one on screen.
const gatewayUpdatedNotification: UserNotificationDelta = {
  type: "user_notification",
  id: 1,
  at: 1_700_000_000,
  agent: "",
  kind: "gateway_updated",
  title: "Updated to v0.1.190",
  body: "Your gateway updated to v0.1.190.",
};

describe("shouldPresentUserNotification", () => {
  const cases: {
    name: string;
    delta: UserNotificationDelta;
    activeAgent: string | null;
    expected: boolean;
  }[] = [
    {
      name: "a needs-user notification always shows, even for the active agent",
      delta: needsUserNotification("alex"),
      activeAgent: "alex",
      expected: true,
    },
    {
      name: "an older gateway's rate-limit notification always shows, even for the active agent",
      delta: rateLimitedUserNotification("alex"),
      activeAgent: "alex",
      expected: true,
    },
    {
      name: "a chat user notification for the active agent defers",
      delta: chatUserNotification("alex"),
      activeAgent: "alex",
      expected: false,
    },
    {
      name: "a chat user notification for a background agent shows",
      delta: chatUserNotification("alex"),
      activeAgent: "robin",
      expected: true,
    },
    {
      name: "a chat user notification shows when no agent is active",
      delta: chatUserNotification("alex"),
      activeAgent: null,
      expected: true,
    },
    {
      name: "the gateway's update announcement shows whatever chat is open",
      delta: gatewayUpdatedNotification,
      activeAgent: "alex",
      expected: true,
    },
  ];

  for (const { name, delta, activeAgent, expected } of cases) {
    it(name, () => {
      expect(shouldPresentUserNotification(delta, activeAgent)).toBe(expected);
    });
  }
});
