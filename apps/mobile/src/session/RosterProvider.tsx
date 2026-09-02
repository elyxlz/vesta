import {
  createContext,
  use,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { AgentRow, DeviceInfo, ReleaseChannel, Tree } from "@vesta/core";
import { devicesEqual, rosterFromTree, rostersEqual, selectDevices } from "@vesta/core";
import { useReplica, useSyncState } from "@vesta/core/react";
import { ControllerContext } from "@/controller/context";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import {
  emptyRosterHold,
  reconcileRosterHold,
  type RosterHold,
  type RosterSnapshot,
} from "./roster-model";

interface RosterValue {
  agents: AgentRow[];
  agentsReady: boolean;
  reachable: boolean;
  gatewayVersion: string | undefined;
  gatewayChannel: ReleaseChannel | undefined;
  managed: boolean;
  updateAvailable: boolean;
  latestVersion: string | null;
  devices: DeviceInfo[];
}

const RosterContext = createContext<RosterValue | null>(null);

// The roster consumes five gateway fields; selecting them with their own equality keeps every
// unrelated gateway delta (e.g. an operation phase tick) from re-identifying the context value.
type GatewaySummary = Omit<RosterSnapshot, "agents">;

function selectGatewaySummary(tree: Tree | null): GatewaySummary | null {
  const gateway = tree?.gateway;
  if (!gateway) return null;
  return {
    gatewayVersion: gateway.version,
    gatewayChannel: gateway.channel,
    managed: gateway.managed,
    updateAvailable: gateway.updateAvailable,
    latestVersion: gateway.latestVersion,
  };
}

function gatewaySummariesEqual(
  a: GatewaySummary | null,
  b: GatewaySummary | null,
): boolean {
  if (a === null || b === null) return a === b;
  return (
    a.gatewayVersion === b.gatewayVersion &&
    a.gatewayChannel === b.gatewayChannel &&
    a.managed === b.managed &&
    a.updateAvailable === b.updateAvailable &&
    a.latestVersion === b.latestVersion
  );
}

// The stale-while-reconnecting hold survives controller epochs and keeps the last complete roster
// visible while the backgrounded controller is null or a foreground controller awaits its snapshot.
// Keying it to the gateway identity prevents a prior gateway's agents bleeding into a new session.
function createRosterHoldStore() {
  let hold: RosterHold = emptyRosterHold;
  return {
    read: (): RosterHold => hold,
    persist: (next: RosterHold): void => {
      hold = next;
    },
  };
}

type RosterHoldStore = ReturnType<typeof createRosterHoldStore>;

const RosterHoldContext = createContext<RosterHoldStore | null>(null);

export function RosterHoldProvider({ children }: { children: ReactNode }) {
  const [store] = useState(createRosterHoldStore);
  return (
    <RosterHoldContext.Provider value={store}>
      {children}
    </RosterHoldContext.Provider>
  );
}

function useRosterHold(): RosterHoldStore {
  const store = use(RosterHoldContext);
  if (!store) {
    throw new Error("RosterProvider must be used within RosterHoldProvider");
  }
  return store;
}

function servedRoster(
  hold: RosterHold,
  live: { reachable: boolean },
): Omit<RosterValue, "devices"> {
  return {
    agents: hold.agents,
    agentsReady: hold.agentsReady,
    reachable: live.reachable,
    gatewayVersion: hold.gatewayVersion,
    gatewayChannel: hold.gatewayChannel,
    managed: hold.managed,
    updateAvailable: hold.updateAvailable,
    latestVersion: hold.latestVersion,
  };
}

// Reconcile the hold for this render (pure; the reducer clears it synchronously on a gateway switch,
// so no stale agents bleed for even one frame) and persist it after commit for the next epoch.
// Memoized end to end: the hold and the served value keep their identity across unrelated renders,
// so useRoster consumers only re-render on real roster changes and the persist effect only fires
// when the hold actually moved.
function useServedRoster(
  store: RosterHoldStore,
  connectionKey: string,
  fresh: RosterSnapshot | null,
  reachable: boolean,
): Omit<RosterValue, "devices"> {
  const hold = useMemo(
    () => reconcileRosterHold(store.read(), connectionKey, fresh),
    [store, connectionKey, fresh],
  );
  useEffect(() => {
    store.persist(hold);
  }, [store, hold]);
  return useMemo(() => servedRoster(hold, { reachable }), [hold, reachable]);
}

// The provider itself never changes type across controller epochs. Only its context value updates,
// so backgrounding cannot unmount the navigation tree or replay native sheet presentation.
export function RosterProvider({ children }: { children: ReactNode }) {
  const controller = use(ControllerContext);
  const { connection } = useSession();
  const store = useRosterHold();
  const connectionKey = connectionKeyOf(connection) ?? "";
  const replica = controller?.replica ?? null;
  const syncState = useSyncState(controller);
  const agents = useReplica(replica, rosterFromTree, rostersEqual);
  const gateway = useReplica(
    replica,
    selectGatewaySummary,
    gatewaySummariesEqual,
  );
  const devices = useReplica(replica, selectDevices, devicesEqual);
  // A non-null gateway means the summary snapshot has populated the tree; only then is the roster fresh.
  const fresh = useMemo<RosterSnapshot | null>(
    () => (gateway ? { agents, ...gateway } : null),
    [agents, gateway],
  );
  const value = useServedRoster(store, connectionKey, fresh, syncState === "open");
  const contextValue = useMemo(
    () => ({ ...value, devices }),
    [value, devices],
  );

  return (
    <RosterContext.Provider value={contextValue}>
      {children}
    </RosterContext.Provider>
  );
}

export function useRoster(): RosterValue {
  const value = use(RosterContext);
  if (!value) throw new Error("useRoster must be used within RosterProvider");
  return value;
}
