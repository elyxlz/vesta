import { act, cleanup, render } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SyncState, Tree } from "@vesta/core";
import {
  ControllerContext,
  ControllerReconnectContext,
} from "@/providers/ControllerProvider/context";
import { useAgentOps } from "@/stores/use-agent-ops";
import { useRestartPending } from "@/stores/use-restart-pending";
import {
  fakeAgentInfo,
  fakeAgentNode,
  fakeController,
  fakeTree,
} from "@/test/fake-controller";
import type { GatewayContextValue } from "./context";
import { GatewayProvider, useGateway } from "./index";

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({ connected: true, initialized: true }),
}));
vi.mock("@/components/AppBehindScreen", () => ({
  AppBehindScreen: () => <div data-testid="app-behind" />,
}));
vi.mock("@/components/GatewayBehindScreen", () => ({
  GatewayBehindScreen: () => <div data-testid="gateway-behind" />,
}));

const BOOT_A = "2026-01-01T00:00:00Z";
const BOOT_B = "2026-01-02T00:00:00Z";

function tree(agents: Record<string, string | null>): Tree {
  return fakeTree({
    agents: Object.fromEntries(
      Object.entries(agents).map(([name, startedAt]) => [
        name,
        fakeAgentNode({ startedAt }),
      ]),
    ),
  });
}

// Hands the latest context value to the test, so it can call the intents and read the derived
// fields without going through rendered copy.
function Probe({ onValue }: { onValue: (value: GatewayContextValue) => void }) {
  const gateway = useGateway();
  useEffect(() => {
    onValue(gateway);
  });
  return <div data-testid="app-body" />;
}

function mount(
  fake: ReturnType<typeof fakeController>,
  reconnect: () => void = () => undefined,
) {
  let value: GatewayContextValue | null = null;
  const utils = render(
    <ControllerReconnectContext.Provider value={reconnect}>
      <ControllerContext.Provider value={fake.controller}>
        <GatewayProvider>
          <Probe
            onValue={(next) => {
              value = next;
            }}
          />
        </GatewayProvider>
      </ControllerContext.Provider>
    </ControllerReconnectContext.Provider>,
  );
  const gateway = (): GatewayContextValue => {
    if (!value) throw new Error("gateway context not rendered");
    return value;
  };
  return { ...utils, gateway };
}

beforeEach(() => {
  useRestartPending.setState({ pending: {} });
  useAgentOps.setState({ states: {} });
});

afterEach(() => {
  cleanup();
});

describe("GatewayProvider", () => {
  it("derives the roster and gateway fields from a replica snapshot", () => {
    const { gateway } = mount(fakeController(tree({ ada: BOOT_A })));

    expect(gateway()).toMatchObject({
      gatewayVersion: "0.2.0",
      gatewayPort: 7777,
      reachable: true,
      agentsFetched: true,
      versionChecked: true,
    });
    expect(gateway().agents.map((row) => row.name)).toEqual(["ada"]);
    // The roster row carries the replica's start time through unchanged.
    expect(gateway().agents[0]?.startedAt).toBe(BOOT_A);
  });

  // Before the snapshot lands the roster is unknown, not empty: agentsFetched false is what keeps
  // NavigationGuard from redirecting to /new on a fresh socket.
  it("reports an unsynced replica as unfetched and unreachable", () => {
    const { gateway } = mount(
      fakeController(null, { syncState: "connecting" }),
    );

    expect(gateway()).toMatchObject({
      agentsFetched: false,
      reachable: false,
      gatewayVersion: "",
      agents: [],
    });
  });

  // A "restart to apply" flag clears once the agent is seen running a different boot, whoever
  // restarted it; the roster delta is the observation.
  it("clears a restart-pending flag once the roster shows the agent rebooted", () => {
    const fake = fakeController(tree({ ada: BOOT_A }));
    useRestartPending.getState().markPending("ada", "files", BOOT_A);
    mount(fake);

    expect(useRestartPending.getState().pending.ada).toBeDefined();

    act(() => {
      fake.emit({
        type: "agent",
        name: "ada",
        info: fakeAgentInfo({ startedAt: BOOT_B }),
      });
    });

    expect(useRestartPending.getState().pending.ada).toBeUndefined();
  });

  // A delete's "deleting" orb ends when the agent leaves the roster, never by flashing idle first.
  it("drops a local op once its agent leaves the roster", () => {
    const fake = fakeController(tree({ ada: BOOT_A, grace: BOOT_A }));
    useAgentOps.getState().setOp("grace", "deleting");
    mount(fake);

    expect(useAgentOps.getState().getOp("grace").operation).toBe("deleting");

    act(() => {
      fake.emit({ type: "agent_removed", name: "grace" });
    });

    expect(useAgentOps.getState().getOp("grace").operation).toBe("idle");
    expect(useAgentOps.getState().getOp("ada").operation).toBe("idle");
  });

  // The version gate routes an incompatible hello to a blocking screen and withholds the app body.
  // Below the served floor is terminal (update the app); newer than the gateway blocks on a gateway
  // update.
  it.each<{ syncState: SyncState; screen: string }>([
    { syncState: "app_behind", screen: "app-behind" },
    { syncState: "gateway_behind", screen: "gateway-behind" },
  ])(
    "routes $syncState to its blocking screen instead of the app",
    ({ syncState, screen }) => {
      const fake = fakeController(tree({ ada: BOOT_A }), { syncState });
      const { queryByTestId } = mount(fake);

      expect(queryByTestId(screen)).not.toBeNull();
      expect(queryByTestId("app-body")).toBeNull();

      // The socket re-hellos into "open" once the versions agree, and the app returns.
      act(() => {
        fake.setSyncState("open");
      });
      expect(queryByTestId(screen)).toBeNull();
      expect(queryByTestId("app-body")).not.toBeNull();
    },
  );

  // A restart drops the gateway like an update does, so the accepted request re-attaches the
  // socket; a refused one leaves the live socket alone.
  it.each([
    { name: "accepted", ok: true },
    { name: "refused", ok: false },
  ])(
    "reconnects after a gateway restart only when the request is $name",
    async ({ ok }) => {
      const fake = fakeController(tree({ ada: BOOT_A }));
      if (!ok) fake.request.mockRejectedValueOnce(new Error("busy"));
      const reconnect = vi.fn();
      const { gateway } = mount(fake, reconnect);

      let result: boolean | null = null;
      await act(async () => {
        result = await gateway().triggerGatewayRestart();
      });

      expect(result).toBe(ok);
      expect(fake.request).toHaveBeenCalledWith("/gateway/restart", {
        method: "POST",
      });
      expect(reconnect).toHaveBeenCalledTimes(ok ? 1 : 0);
    },
  );
});
