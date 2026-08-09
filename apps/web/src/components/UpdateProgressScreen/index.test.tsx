import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { GatewayOperation } from "@vesta/core";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import { UpdateProgressScreen } from "./index";

function renderScreen(overrides: Partial<GatewayContextValue>) {
  const value: GatewayContextValue = { ...disconnectedValue, ...overrides };
  return render(
    <GatewayContext.Provider value={value}>
      <UpdateProgressScreen />
    </GatewayContext.Provider>,
  );
}

const UPDATE: GatewayOperation = {
  kind: "update",
  phase: "snapshotting",
  agent: "ada",
  done: 1,
  total: 4,
  targetVersion: "0.1.190",
  warnings: [],
  error: null,
};

afterEach(cleanup);

describe("UpdateProgressScreen", () => {
  it("names the release an update is installing and the agent it is backing up", () => {
    const { container } = renderScreen({ gatewayOperation: UPDATE });
    expect(container.textContent).toContain("updating to v0.1.190");
    expect(container.textContent).toContain("backing up ada 2/4");
  });

  it("says a restart is a restart, naming no release", () => {
    const { container } = renderScreen({
      gatewayOperation: {
        ...UPDATE,
        kind: "restart",
        phase: "restarting",
        agent: null,
        done: null,
        total: null,
        targetVersion: null,
      },
    });
    expect(container.textContent).toContain("restarting the gateway");
    expect(container.textContent).not.toContain("updating to");
    expect(container.textContent).not.toContain("backs up every agent");
  });

  it("offers retry and dismiss on a failure", () => {
    const { getByRole, container } = renderScreen({
      gatewayOperation: {
        ...UPDATE,
        phase: "failed",
        error: "while installing: curl failed",
      },
    });
    expect(container.textContent).toContain("update failed");
    expect(container.textContent).toContain("while installing: curl failed");
    expect(getByRole("button", { name: "retry" })).toBeTruthy();
    expect(getByRole("button", { name: "dismiss" })).toBeTruthy();
  });
});
