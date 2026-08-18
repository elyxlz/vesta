import { describe, expect, it } from "vitest";
import { loadRegistry } from "@vesta/visual/registry";
import { DRIVES } from "./drives";

describe("web visual registry", () => {
  it("has exactly one drive per registered scenario", async () => {
    const registry = await loadRegistry("web");
    const ids = registry.scenarios.map((scenario) => scenario.id).sort();
    expect(ids).toEqual(Object.keys(DRIVES).sort());
  });

  it("carries a title, description, and group for every card", async () => {
    const registry = await loadRegistry("web");
    for (const scenario of registry.scenarios) {
      expect(scenario.title.length).toBeGreaterThan(0);
      expect(scenario.description.length).toBeGreaterThan(0);
      expect(["Onboarding", "Agent settings"]).toContain(scenario.group);
    }
  });
});
