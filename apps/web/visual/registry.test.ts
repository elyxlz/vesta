import { describe, expect, it } from "vitest";
import { loadRegistry } from "@vesta/visual/registry";
import { SCENARIOS } from "./drives";

const GROUPS = [
  "Onboarding",
  "Home",
  "Gateway update",
  "Agent",
  "Chat",
  "Logs",
  "Agent settings",
  "App settings",
  "Connect",
  "Agent modals",
];

describe("web visual registry", () => {
  it("has exactly one drive per registered scenario", async () => {
    const registry = await loadRegistry("web");
    const ids = registry.scenarios.map((scenario) => scenario.id).sort();
    expect(ids).toEqual(Object.keys(SCENARIOS).sort());
  });

  it("carries a title, description, and group for every card", async () => {
    const registry = await loadRegistry("web");
    for (const scenario of registry.scenarios) {
      expect(scenario.title.length).toBeGreaterThan(0);
      expect(scenario.description.length).toBeGreaterThan(0);
      expect(GROUPS).toContain(scenario.group);
    }
  });
});
