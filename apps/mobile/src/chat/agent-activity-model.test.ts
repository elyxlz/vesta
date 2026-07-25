import { describe, expect, it } from "vitest";
import type { Tree } from "@vesta/core";
import {
  selectAgentActivitySnapshot,
  servedAgentActivity,
} from "./agent-activity-model";

describe("agent activity snapshots", () => {
  it("is not ready until the controller replica receives a snapshot", () => {
    expect(selectAgentActivitySnapshot(null, true, "scout")).toEqual({
      state: "idle",
      ready: false,
    });
  });

  it("serves held activity until the new replica is ready", () => {
    expect(
      servedAgentActivity({ state: "idle", ready: false }, "thinking"),
    ).toBe("thinking");
    expect(
      servedAgentActivity({ state: "idle", ready: true }, "thinking"),
    ).toBe("idle");
  });

  it("reads activity from a populated replica", () => {
    const tree = {
      agents: {
        scout: { info: { activityState: "thinking" } },
      },
    } as unknown as Tree;
    expect(selectAgentActivitySnapshot(tree, true, "scout")).toEqual({
      state: "thinking",
      ready: true,
    });
  });
});
