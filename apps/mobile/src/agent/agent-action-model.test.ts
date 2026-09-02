import { describe, expect, it } from "vitest";
import { agentActionRequest } from "./agent-action-model";

describe("agentActionRequest", () => {
  it.each([
    ["start", "starting"],
    ["restart", "starting"],
    ["stop", "stopping"],
    ["backup", "backing-up"],
    ["delete", "deleting"],
  ] as const)("holds %s on the agent as %s", (action, request) => {
    expect(agentActionRequest(action)).toBe(request);
  });
});
