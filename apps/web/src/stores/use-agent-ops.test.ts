import { beforeEach, describe, expect, it } from "vitest";

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
