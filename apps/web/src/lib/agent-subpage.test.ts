import { describe, expect, it } from "vitest";
import { agentSubpage } from "./agent-subpage";

describe("agentSubpage", () => {
  it("maps the dashboard and chat paths to no subpage", () => {
    expect(agentSubpage("/agent/ada", "ada")).toBeNull();
    expect(agentSubpage("/agent/ada/chat", "ada")).toBeNull();
  });

  it("maps the logs and settings paths to their subpage", () => {
    expect(agentSubpage("/agent/ada/logs", "ada")).toBe("logs");
    expect(agentSubpage("/agent/ada/settings", "ada")).toBe("settings");
  });

  it("encodes the agent name the way the router links do", () => {
    expect(agentSubpage("/agent/a%20b/logs", "a b")).toBe("logs");
  });
});
