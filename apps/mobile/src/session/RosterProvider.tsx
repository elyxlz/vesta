import {
  createContext,
  use,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { Controller, Tree } from "@vesta/core";
import { useReplica, useSyncState } from "@vesta/core/react";
import type { ConnectionConfig } from "@/api/types";
import { ControllerContext } from "@/controller/context";
import { useSession } from "@/session/SessionProvider";
import {
  emptyRosterHold,
  reconcileRosterHold,
  rosterFromTree,
  rostersEqual,
  type AgentRow,
  type RosterHold,
  type RosterSnapshot,
} from "./roster-model";

interface RosterValue {
  agents: AgentRow[];
  agentsReady: boolean;
  reachable: boolean;
  gatewayVersion: string | undefined;
  managed: boolean;
  updateAvailable: boolean;
  latestVersion: string | null;
  compatible: boolean;
}

const RosterContext = createContext<RosterValue | null>(null);

// The stale-while-reconnecting hold lives in a store ABOVE ControllerProvider: RosterProvider remounts
// on every background/foreground (ControllerProvider swaps its wrapper type when the controller flips
// null), so a hold kept inside it would reset and blank the roster. Keyed to the gateway identity, the
// reducer clears it on a gateway switch so a prior gateway's agents never bleed onto the next.
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

function selectGateway(tree: Tree | null) {
  return tree?.gateway ?? null;
}

function connectionKeyOf(connection: ConnectionConfig | null): string {
  return connection ? `${connection.url}\n${String(connection.hosted)}` : "";
}

function servedRoster(
  hold: RosterHold,
  live: { reachable: boolean; compatible: boolean },
): RosterValue {
  return {
    agents: hold.agents,
    agentsReady: hold.agentsReady,
    reachable: live.reachable,
    gatewayVersion: hold.gatewayVersion,
    managed: hold.managed,
    updateAvailable: hold.updateAvailable,
    latestVersion: hold.latestVersion,
    compatible: live.compatible,
  };
}

// Reconcile the hold for this render (pure; the reducer clears it synchronously on a gateway switch,
// so no stale agents bleed for even one frame) and persist it after commit so the next epoch/remount
// reads the last-known roster instead of an empty one.
function useServedRoster(
  store: RosterHoldStore,
  connectionKey: string,
  fresh: RosterSnapshot | null,
  live: { reachable: boolean; compatible: boolean },
): RosterValue {
  const hold = reconcileRosterHold(store.read(), connectionKey, fresh);
  useEffect(() => {
    store.persist(hold);
  }, [store, hold]);
  return servedRoster(hold, live);
}

function LiveRoster({
  controller,
  connectionKey,
  store,
  children,
}: {
  controller: Controller;
  connectionKey: string;
  store: RosterHoldStore;
  children: ReactNode;
}) {
  const agents = useReplica(controller.replica, rosterFromTree, rostersEqual);
  const gateway = useReplica(controller.replica, selectGateway);
  const syncState = useSyncState(controller);
  // A non-null gateway means the summary snapshot has populated the tree; only then is the roster fresh.
  const fresh: RosterSnapshot | null = gateway
    ? {
        agents,
        gatewayVersion: gateway.version,
        managed: gateway.managed,
        updateAvailable: gateway.updateAvailable,
        latestVersion: gateway.latestVersion,
      }
    : null;
  const value = useServedRoster(store, connectionKey, fresh, {
    reachable: syncState === "open",
    compatible: syncState !== "incompatible",
  });
  return (
    <RosterContext.Provider value={value}>{children}</RosterContext.Provider>
  );
}

function DisconnectedRoster({
  connectionKey,
  store,
  children,
}: {
  connectionKey: string;
  store: RosterHoldStore;
  children: ReactNode;
}) {
  const value = useServedRoster(store, connectionKey, null, {
    reachable: false,
    compatible: true,
  });
  return (
    <RosterContext.Provider value={value}>{children}</RosterContext.Provider>
  );
}

// Tolerates the null controller context (pre-connect / backgrounded): read it nullable rather than
// useController(), which throws when there is no live controller. The last-known roster keeps being
// served while the controller is gone (reachable stays honest at false).
export function RosterProvider({ children }: { children: ReactNode }) {
  const controller = use(ControllerContext);
  const { connection } = useSession();
  const store = useRosterHold();
  const connectionKey = connectionKeyOf(connection);
  if (!controller) {
    return (
      <DisconnectedRoster connectionKey={connectionKey} store={store}>
        {children}
      </DisconnectedRoster>
    );
  }
  return (
    <LiveRoster
      controller={controller}
      connectionKey={connectionKey}
      store={store}
    >
      {children}
    </LiveRoster>
  );
}

export function useRoster(): RosterValue {
  const value = use(RosterContext);
  if (!value) throw new Error("useRoster must be used within RosterProvider");
  return value;
}
