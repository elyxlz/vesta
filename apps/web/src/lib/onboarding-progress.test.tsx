// Exercises the real sessionStorage-backed helper, so it runs in the jsdom project (storage
// present) — hence .test.tsx despite having no JSX. The .test.ts (node) project has no storage.
import { beforeEach, describe, expect, it } from "vitest";

import { loadOnboarding, saveOnboarding } from "./onboarding-progress";

beforeEach(() => {
  sessionStorage.clear();
});

describe("onboarding progress", () => {
  it("round-trips the name and personality across a reload", () => {
    saveOnboarding({ agentName: "luna", personality: "warm" });
    expect(loadOnboarding()).toEqual({
      agentName: "luna",
      personality: "warm",
    });
  });

  it("keeps a name saved before a personality is chosen", () => {
    saveOnboarding({ agentName: "luna", personality: null });
    expect(loadOnboarding()).toEqual({ agentName: "luna", personality: null });
  });

  it("treats an entry with no usable name as no progress", () => {
    sessionStorage.setItem(
      "vesta:onboarding",
      JSON.stringify({ agentName: "", personality: "warm" }),
    );
    expect(loadOnboarding()).toBeNull();
  });

  it("ignores a corrupt payload rather than throwing", () => {
    sessionStorage.setItem("vesta:onboarding", "{not json");
    expect(loadOnboarding()).toBeNull();
  });
});
