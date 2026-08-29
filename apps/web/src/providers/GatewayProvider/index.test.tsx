import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentInfo as CoreAgentInfo, Tree } from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import { useAgentOps } from "@/stores/use-agent-ops";
import { useRestartPending } from "@/stores/use-restart-pending";
import {
  fakeController,
  fakeGatewayInfo,
  fakeTree,
} from "@/test/fake-controller";
import { GatewayProvider, useGateway } from "./index";

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({ connected: true, initialized: true }),
}));

function agentInfo(overrides: Partial<CoreAgentInfo> = {}): CoreAgentInfo {
  return {
    status: "alive",
    activityState: "idle",
    buildPhase: null,
    operation: null,
    startedAt: "2026-01-01T00:00:00Z",
    services: {},
    ...overrides,
  };
}

function tree(agentNames: string[]): Tree {
  return fakeTree({
    gateway: fakeGatewayInfo({ version: "0.2.0" }),
    agents: Object.fromEntries(
      agentNames.map((name) => [
        name,
        { info: agentInfo(), notifications: { pending: [] } },
      ]),
    ),
  });
}

function Probe() {
  const gateway = useGateway();
  return (
    <dl>
      <dd data-testid="version">{gateway.gatewayVersion}</dd>
      <dd data-testid="port">{gateway.gatewayPort}</dd>
      <dd data-testid="reachable">{String(gateway.reachable)}</dd>
      <dd data-testid="fetched">{String(gateway.agentsFetched)}</dd>
      <dd data-testid="names">
        {gateway.agents.map((row) => row.name).join(",")}
      </dd>
      <dd data-testid="started">{gateway.agents[0]?.startedAt ?? ""}</dd>
    </dl>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("GatewayProvider", () => {
  it("derives the roster and gateway fields from a replica snapshot", () => {
    const { controller } = fakeController(tree(["ada"]));

    const { getByTestId } = render(
      <ControllerContext.Provider value={controller}>
        <GatewayProvider>
          <Probe />
        </GatewayProvider>
      </ControllerContext.Provider>,
    );

    expect(getByTestId("version").textContent).toBe("0.2.0");
    expect(getByTestId("port").textContent).toBe("7777");
    expect(getByTestId("reachable").textContent).toBe("true");
    expect(getByTestId("fetched").textContent).toBe("true");
    expect(getByTestId("names").textContent).toBe("ada");
    // The roster row carries the replica's start time through unchanged.
    expect(getByTestId("started").textContent).toBe("2026-01-01T00:00:00Z");
  });

  it("reconciles the ops + restart-pending stores when the roster changes", () => {
    const { controller } = fakeController(tree(["ada"]));
    const restartSpy = vi.spyOn(useRestartPending.getState(), "reconcile");
    const opsSpy = vi.spyOn(useAgentOps.getState(), "reconcile");

    const { getByTestId } = render(
      <ControllerContext.Provider value={controller}>
        <GatewayProvider>
          <Probe />
        </GatewayProvider>
      </ControllerContext.Provider>,
    );

    expect(restartSpy).toHaveBeenCalledWith([
      expect.objectContaining({ name: "ada" }),
    ]);
    expect(opsSpy).toHaveBeenCalledTimes(1);

    act(() => {
      controller.replica.applyDelta({
        type: "agent",
        name: "grace",
        info: agentInfo(),
      });
    });

    expect(getByTestId("names").textContent).toBe("ada,grace");
    expect(restartSpy).toHaveBeenCalledTimes(2);
    expect(opsSpy).toHaveBeenCalledTimes(2);
  });
});
