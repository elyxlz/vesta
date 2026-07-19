import { createContext, use, type ReactNode } from "react";
import type { Controller, Tree } from "@vesta/core";
import { useReplica, useSyncState } from "@vesta/core/react";
import { ControllerContext } from "@/controller/context";
import { rosterFromTree, rostersEqual, type AgentRow } from "./roster-model";

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

// Before connect and while backgrounded the controller context is null; the roster mirrors
// web's disconnected gateway value so consumers render without a live tree.
const disconnectedRoster: RosterValue = {
  agents: [],
  agentsReady: false,
  reachable: false,
  gatewayVersion: undefined,
  managed: false,
  updateAvailable: false,
  latestVersion: null,
  compatible: true,
};

const RosterContext = createContext<RosterValue | null>(null);

function selectGateway(tree: Tree | null) {
  return tree?.gateway ?? null;
}

function LiveRoster({
  controller,
  children,
}: {
  controller: Controller;
  children: ReactNode;
}) {
  const agents = useReplica(controller.replica, rosterFromTree, rostersEqual);
  const gateway = useReplica(controller.replica, selectGateway);
  const syncState = useSyncState(controller);
  const value: RosterValue = {
    agents,
    // The summary snapshot populates the gateway branch, so a non-null gateway means the tree is ready.
    agentsReady: gateway !== null,
    reachable: syncState === "open",
    gatewayVersion: gateway?.version,
    managed: gateway?.managed ?? false,
    updateAvailable: gateway?.updateAvailable ?? false,
    latestVersion: gateway?.latestVersion ?? null,
    compatible: syncState !== "incompatible",
  };
  return (
    <RosterContext.Provider value={value}>{children}</RosterContext.Provider>
  );
}

// Tolerates the null controller context (pre-connect / backgrounded): read it nullable rather
// than useController(), which throws when there is no live controller.
export function RosterProvider({ children }: { children: ReactNode }) {
  const controller = use(ControllerContext);
  if (!controller) {
    return (
      <RosterContext.Provider value={disconnectedRoster}>
        {children}
      </RosterContext.Provider>
    );
  }
  return <LiveRoster controller={controller}>{children}</LiveRoster>;
}

export function useRoster(): RosterValue {
  const value = use(RosterContext);
  if (!value) throw new Error("useRoster must be used within RosterProvider");
  return value;
}
