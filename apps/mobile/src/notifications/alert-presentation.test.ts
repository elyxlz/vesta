import { describe, expect, it } from "vitest";
import type { AlertDelta } from "@vesta/core";
import { shouldPresentAlert } from "./alert-presentation";

function chatAlert(agent: string): AlertDelta {
  return { type: "alert", agent, kind: "message", title: agent, body: "hi" };
}

function rateLimitedAlert(agent: string): AlertDelta {
  return {
    type: "alert",
    agent,
    kind: "rate_limited",
    title: agent,
    body: "throttled",
  };
}

describe("shouldPresentAlert", () => {
  const cases: {
    name: string;
    delta: AlertDelta;
    activeAgent: string | null;
    expected: boolean;
  }[] = [
    {
      name: "a rate-limit alert always shows, even for the active agent",
      delta: rateLimitedAlert("alex"),
      activeAgent: "alex",
      expected: true,
    },
    {
      name: "a chat alert for the active agent defers",
      delta: chatAlert("alex"),
      activeAgent: "alex",
      expected: false,
    },
    {
      name: "a chat alert for a background agent shows",
      delta: chatAlert("alex"),
      activeAgent: "robin",
      expected: true,
    },
    {
      name: "a chat alert shows when no agent is active",
      delta: chatAlert("alex"),
      activeAgent: null,
      expected: true,
    },
  ];

  for (const { name, delta, activeAgent, expected } of cases) {
    it(name, () => {
      expect(shouldPresentAlert(delta, activeAgent)).toBe(expected);
    });
  }
});
