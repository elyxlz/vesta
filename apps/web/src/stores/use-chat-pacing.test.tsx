// Exercises the real persisted store, so it runs in the jsdom project (localStorage present).
import { beforeEach, describe, expect, it } from "vitest";
import { useChatPacing } from "./use-chat-pacing";

beforeEach(() => {
  localStorage.clear();
  useChatPacing.setState({ byAgent: {} });
});

describe("useChatPacing", () => {
  it("defaults every agent to natural pacing", () => {
    expect(useChatPacing.getState().naturalFor("ada")).toBe(true);
  });

  it("keeps each agent's switch independent and persists it", () => {
    useChatPacing.getState().setNatural("ada", false);
    expect(useChatPacing.getState().naturalFor("ada")).toBe(false);
    expect(useChatPacing.getState().naturalFor("ben")).toBe(true);
    expect(localStorage.getItem("chat-natural-pacing-by-agent")).toBe(
      JSON.stringify({ ada: false }),
    );
  });
});
