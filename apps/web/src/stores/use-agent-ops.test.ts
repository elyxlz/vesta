import { beforeEach, describe, expect, it } from "vitest";

import { useAgentOps } from "./use-agent-ops";

beforeEach(() => {
  useAgentOps.setState({ states: {} });
});

describe("useAgentOps.withOp", () => {
  it("clears the op once the operation succeeds", async () => {
    await useAgentOps
      .getState()
      .withOp("ada", "starting", async () => {}, "start failed");
    expect(useAgentOps.getState().getOp("ada").operation).toBe("idle");
  });

  it("keeps the op after success when asked, so a deleted agent's card stays in its deleting look", async () => {
    await useAgentOps
      .getState()
      .withOp("ada", "deleting", async () => {}, "delete failed", {
        keepOnSuccess: true,
      });
    expect(useAgentOps.getState().getOp("ada").operation).toBe("deleting");
  });

  it("returns to idle with the error surfaced when the operation throws", async () => {
    await useAgentOps.getState().withOp(
      "ada",
      "deleting",
      async () => {
        throw new Error("boom");
      },
      "delete failed",
      { keepOnSuccess: true },
    );
    const op = useAgentOps.getState().getOp("ada");
    expect(op.operation).toBe("idle");
    expect(op.error).toBe("boom");
  });

  it("refuses to start while another op is in flight", async () => {
    useAgentOps.getState().setOp("ada", "deleting");
    await useAgentOps
      .getState()
      .withOp("ada", "starting", async () => {}, "start failed");
    expect(useAgentOps.getState().getOp("ada").operation).toBe("deleting");
  });
});

describe("useAgentOps.reconcile", () => {
  it("drops op state for agents that no longer exist and keeps the rest", () => {
    useAgentOps.getState().setOp("ada", "deleting");
    useAgentOps.getState().setOp("bob", "starting");
    useAgentOps.getState().reconcile([{ name: "bob" }]);
    expect(useAgentOps.getState().states["ada"]).toBeUndefined();
    expect(useAgentOps.getState().getOp("bob").operation).toBe("starting");
  });

  it("leaves state untouched when every op belongs to a live agent", () => {
    useAgentOps.getState().setOp("ada", "stopping");
    const before = useAgentOps.getState().states;
    useAgentOps.getState().reconcile([{ name: "ada" }]);
    expect(useAgentOps.getState().states).toBe(before);
  });
});
