import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createReplica } from "@vesta/core";
import type {
  AgentInfo as CoreAgentInfo,
  Controller,
  GatewayInfo,
  Tree,
} from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import { useAgentOps } from "@/stores/use-agent-ops";
import { useRestartPending } from "@/stores/use-restart-pending";
import { GatewayProvider, useGateway } from "./index";

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({ connected: true, initialized: true }),
}));

function gatewayInfo(overrides: Partial<GatewayInfo> = {}): GatewayInfo {
  return {
    version: "0.2.0",
    channel: "stable",
    autoUpdate: true,
    port: 7777,
    lan: { exposed: false, url: null },
    tunnelUrl: null,
    updateAvailable: false,
    latestVersion: null,
    managed: false,
    ...overrides,
  };
}

function agentInfo(overrides: Partial<CoreAgentInfo> = {}): CoreAgentInfo {
  return {
    status: "alive",
    activityState: "idle",
    buildPhase: null,
    startedAt: "2026-01-01T00:00:00Z",
    services: {},
    ...overrides,
  };
}

function tree(agentNames: string[]): Tree {
  return {
    gateway: gatewayInfo(),
    agents: Object.fromEntries(
      agentNames.map((name) => [
        name,
        { info: agentInfo(), notifications: { pending: [] } },
      ]),
    ),
  };
}

// A controller stub over a real replica: only the replica + a fixed-"open" sync sub-store are
// exercised by the gateway provider, so the rest is inert.
function stubController(replica: ReturnType<typeof createReplica>): Controller {
  return {
    replica,
    http: {} as Controller["http"],
    watch: () => undefined,
    unwatch: () => undefined,
    reauth: () => undefined,
    subscribeDeltas: () => () => undefined,
    getSyncState: () => "open",
    subscribeSyncState: () => () => undefined,
    close: () => undefined,
  };
}

function Probe() {
  const gateway = useGateway();
  return (
    <dl>
      <dd data-testid="version">{gateway.gatewayVersion}</dd>
      <dd data-testid="port">{gateway.gatewayPort}</dd>
      <dd data-testid="reachable">{String(gateway.reachable)}</dd>
      <dd data-testid="fetched">{String(gateway.agentsFetched)}</dd>
      <dd data-testid="versionChecked">{String(gateway.versionChecked)}</dd>
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
    const replica = createReplica();
    replica.applySnapshot(tree(["ada"]));

    const { getByTestId } = render(
      <ControllerContext.Provider value={stubController(replica)}>
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
    // The roster row carries the replica's start time through unchanged (null for a never-started agent).
    expect(getByTestId("started").textContent).toBe("2026-01-01T00:00:00Z");
  });

  it("reconciles the ops + restart-pending stores when the roster changes", () => {
    const replica = createReplica();
    replica.applySnapshot(tree(["ada"]));
    const restartSpy = vi.spyOn(useRestartPending.getState(), "reconcile");
    const opsSpy = vi.spyOn(useAgentOps.getState(), "reconcile");

    const { getByTestId } = render(
      <ControllerContext.Provider value={stubController(replica)}>
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
      replica.applyDelta({ type: "agent", name: "grace", info: agentInfo() });
    });

    expect(getByTestId("names").textContent).toBe("ada,grace");
    expect(restartSpy).toHaveBeenCalledTimes(2);
    expect(opsSpy).toHaveBeenCalledTimes(2);
  });

  it("holds the checking value (versionChecked false) with no controller yet", () => {
    const { getByTestId } = render(
      <ControllerContext.Provider value={null}>
        <GatewayProvider>
          <Probe />
        </GatewayProvider>
      </ControllerContext.Provider>,
    );

    expect(getByTestId("versionChecked").textContent).toBe("false");
    expect(getByTestId("reachable").textContent).toBe("false");
    expect(getByTestId("fetched").textContent).toBe("false");
    expect(getByTestId("names").textContent).toBe("");
  });
});
