import { describe, expect, it } from "vitest";
import type { UserNotificationDelta } from "@vesta/core";
import { shouldPresentUserNotification } from "./user-notification-presentation";

function chatUserNotification(
  agent: string,
  room?: string,
): UserNotificationDelta {
  return {
    type: "user_notification",
    id: 1,
    at: 1_700_000_000,
    agent,
    kind: "message",
    title: agent,
    body: "hi",
    ...(room === undefined ? {} : { room }),
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

// The gateway's own announcement names no agent, so it can never be the open conversation.
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
    activeRoom: string | null;
    expected: boolean;
  }[] = [
    {
      name: "a needs-user notification always shows, even for the open conversation",
      delta: needsUserNotification("alex"),
      activeRoom: "dm:alex",
      expected: true,
    },
    {
      name: "an older gateway's rate-limit notification always shows",
      delta: rateLimitedUserNotification("alex"),
      activeRoom: "dm:alex",
      expected: true,
    },
    {
      name: "a reply in the open room defers",
      delta: chatUserNotification("alex", "dm:alex"),
      activeRoom: "dm:alex",
      expected: false,
    },
    {
      name: "a group reply while a different conversation is open shows",
      delta: chatUserNotification("alex", "grp-trip"),
      activeRoom: "dm:alex",
      expected: true,
    },
    {
      name: "a group reply in the group being read defers",
      delta: chatUserNotification("alex", "grp-trip"),
      activeRoom: "grp-trip",
      expected: false,
    },
    {
      name: "a notice naming no room falls back to the agent's own conversation",
      delta: chatUserNotification("alex"),
      activeRoom: "dm:alex",
      expected: false,
    },
    {
      name: "a reply shows when no conversation is open",
      delta: chatUserNotification("alex", "dm:alex"),
      activeRoom: null,
      expected: true,
    },
    {
      name: "the gateway's update announcement shows whatever chat is open",
      delta: gatewayUpdatedNotification,
      activeRoom: "dm:alex",
      expected: true,
    },
  ];

  for (const { name, delta, activeRoom, expected } of cases) {
    it(name, () => {
      expect(shouldPresentUserNotification(delta, activeRoom)).toBe(expected);
    });
  }
});
