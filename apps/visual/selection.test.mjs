import { describe, expect, it } from "vitest";
import { captureSelection, selectRegistry } from "./selection.mjs";
import { comparisonTargets } from "./comparison.mjs";
import { referenceIndex } from "./references.mjs";

const registry = {
  family: "web",
  scenarios: [
    { id: "page-settings", page: "settings" },
    { id: "settings-error" },
  ],
};

describe("capture selection", () => {
  it("includes pages and detailed states by default, with optional suite filters", () => {
    expect(captureSelection({})).toEqual({ suite: "all", page: "" });
    expect(selectRegistry(registry).scenarios).toEqual(registry.scenarios);
    expect(selectRegistry(registry, { suite: "pages", page: "" }).scenarios).toEqual([
      { id: "page-settings", page: "settings" },
    ]);
    expect(
      selectRegistry(registry, { suite: "states", page: "" }).scenarios,
    ).toEqual([{ id: "settings-error" }]);
    expect(
      selectRegistry(registry, { suite: "all", page: "" }).scenarios,
    ).toHaveLength(2);
  });
  it("includes voice conversation references and pixel comparisons without opting in", async () => {
    const index = await referenceIndex(captureSelection({}), "ios");
    expect(index.references).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "agent-chat-conversation", platform: "ios" }),
    ]));
    const selection = captureSelection({ VISUAL_PAGE: "agent-chat-conversation" });
    expect(await comparisonTargets("ios", selection)).toEqual([
      { platform: "ios", name: "agent-chat-conversation.png" },
    ]);
    expect((await referenceIndex(selection, "ios")).references).toHaveLength(1);
  });
  it("rejects typos instead of running a successful empty capture", () => {
    expect(() => captureSelection({ VISUAL_SUITE: "pagez" })).toThrow(
      "Unknown visual suite",
    );
    expect(() =>
      selectRegistry(registry, { suite: "pages", page: "missing" }),
    ).toThrow("No web page");
  });
  it("scopes comparison and agent references to one page and platform", async () => {
    const selection = { suite: "pages", page: "settings" };
    expect(await comparisonTargets("web", selection)).toEqual([
      { platform: "web", name: "page-settings.png" },
    ]);
    const index = await referenceIndex(selection, "web");
    expect(index.references).toHaveLength(1);
    expect(index.references[0]).toMatchObject({
      page: "settings",
      platform: "web",
      refresh: "npm run visual:capture -- web --suite pages --page settings",
    });
    await expect(
      referenceIndex({ suite: "pages", page: "typo" }),
    ).rejects.toThrow("No page matches");
  });
});
