import { describe, expect, it } from "vitest";
import type { UserNotificationDelta } from "@vesta/core";
import { shouldPresentUserNotification } from "./user-notification-presentation";

function chatUserNotification(agent: string): UserNotificationDelta {
  return { type: "user_notification", agent, kind: "message", title: agent, body: "hi" };
}

function rateLimitedUserNotification(agent: string): UserNotificationDelta {
  return {
    type: "user_notification",
    agent,
    kind: "rate_limited",
    title: agent,
    body: "throttled",
  };
}

describe("shouldPresentUserNotification", () => {
  const cases: {
    name: string;
    delta: UserNotificationDelta;
    activeAgent: string | null;
    expected: boolean;
  }[] = [
    {
      name: "a rate-limit user notification always shows, even for the active agent",
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
  ];

  for (const { name, delta, activeAgent, expected } of cases) {
    it(name, () => {
      expect(shouldPresentUserNotification(delta, activeAgent)).toBe(expected);
    });
  }
});
