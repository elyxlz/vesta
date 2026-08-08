import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { fetchClaudeModels, fetchAgentClaudeModels } from "./claude";

describe("claude model fetch", () => {
  it("posts credentials to the onboarding endpoint", async () => {
    const spy = vi
      .spyOn(client, "apiJson")
      .mockResolvedValue([
        { slug: "claude-opus-5", label: "Claude Opus 5", author: "Anthropic" },
      ]);
    const models = await fetchClaudeModels("blob");
    expect(spy).toHaveBeenCalledWith(
      "/providers/claude/models",
      expect.objectContaining({ method: "POST" }),
    );
    expect(models[0]?.slug).toBe("claude-opus-5");
  });

  it("gets the agent endpoint for settings", async () => {
    const spy = vi.spyOn(client, "apiJson").mockResolvedValue([]);
    await fetchAgentClaudeModels("apollo");
    expect(spy).toHaveBeenCalledWith("/agents/apollo/provider/models");
  });
});
