import { createContext, use, useEffect, useState, type ReactNode } from "react";
import type { AgentRow, ReleaseChannel, Tree } from "@vesta/core";
import { rosterFromTree, rostersEqual } from "@vesta/core";
import { ControllerContext } from "@/controller/context";
import {
  useOptionalControllerReplica,
  useOptionalControllerSyncState,
} from "@/controller/optional-controller-store";
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
}

const RosterContext = createContext<RosterValue | null>(null);

function selectGateway(tree: Tree | null) {
  return tree?.gateway ?? null;
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
): RosterValue {
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
function useServedRoster(
  store: RosterHoldStore,
  connectionKey: string,
  fresh: RosterSnapshot | null,
  live: { reachable: boolean },
): RosterValue {
  const hold = reconcileRosterHold(store.read(), connectionKey, fresh);
  useEffect(() => {
    store.persist(hold);
  }, [store, hold]);
  return servedRoster(hold, live);
}

// The provider itself never changes type across controller epochs. Only its context value updates,
// so backgrounding cannot unmount the navigation tree or replay native sheet presentation.
export function RosterProvider({ children }: { children: ReactNode }) {
  const controller = use(ControllerContext);
  const { connection } = useSession();
  const store = useRosterHold();
  const connectionKey = connectionKeyOf(connection) ?? "";
  const syncState = useOptionalControllerSyncState(controller);
  const agents = useOptionalControllerReplica(
    controller,
    rosterFromTree,
    rostersEqual,
  );
  const gateway = useOptionalControllerReplica(controller, selectGateway);
  // A non-null gateway means the summary snapshot has populated the tree; only then is the roster fresh.
  const fresh: RosterSnapshot | null = gateway
    ? {
        agents,
        gatewayVersion: gateway.version,
        gatewayChannel: gateway.channel,
        managed: gateway.managed,
        updateAvailable: gateway.updateAvailable,
        latestVersion: gateway.latestVersion,
      }
    : null;
  const value = useServedRoster(store, connectionKey, fresh, {
    reachable: syncState === "open",
  });

  return (
    <RosterContext.Provider value={value}>{children}</RosterContext.Provider>
  );
}

export function useRoster(): RosterValue {
  const value = use(RosterContext);
  if (!value) throw new Error("useRoster must be used within RosterProvider");
  return value;
}
