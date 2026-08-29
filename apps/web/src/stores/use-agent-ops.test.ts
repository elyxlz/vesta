import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentOps } from "./use-agent-ops";

beforeEach(() => {
  useAgentOps.setState({ states: {} });
});

describe("useAgentOps.reconcile", () => {
  it("drops op state for a deleted agent so its deleting orb ends when it leaves the list", () => {
    useAgentOps.getState().setOp("ada", "deleting");
    useAgentOps.getState().setOp("bob", "starting");
    useAgentOps.getState().reconcile([{ name: "bob" }]);
    expect(useAgentOps.getState().states.ada).toBeUndefined();
    expect(useAgentOps.getState().getOp("bob").operation).toBe("starting");
  });

  it("keeps a deleting op while its agent is still present, so the orb stays red", () => {
    useAgentOps.getState().setOp("ada", "deleting");
    useAgentOps.getState().reconcile([{ name: "ada" }]);
    expect(useAgentOps.getState().getOp("ada").operation).toBe("deleting");
  });
});

describe("useAgentOps.withOp", () => {
  it("ignores a second submit while the first is in flight", async () => {
    let finish: () => void = () => undefined;
    const first = useAgentOps.getState().withOp(
      "ada",
      "starting",
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
      "could not start",
    );
    const second = vi.fn(() => Promise.resolve());
    await useAgentOps
      .getState()
      .withOp("ada", "stopping", second, "could not stop");
    expect(second).not.toHaveBeenCalled();
    expect(useAgentOps.getState().getOp("ada").operation).toBe("starting");

    finish();
    await first;
    expect(useAgentOps.getState().getOp("ada").operation).toBe("idle");
  });

  it("lands the failure message and returns to idle when the action throws", async () => {
    await useAgentOps
      .getState()
      .withOp(
        "ada",
        "starting",
        () => Promise.reject(new Error("docker down")),
        "could not start",
      );
    expect(useAgentOps.getState().getOp("ada")).toEqual({
      operation: "idle",
      error: "docker down",
    });
  });
});
