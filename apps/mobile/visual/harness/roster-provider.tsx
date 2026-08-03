import { createContext, use, type ReactNode } from "react";
import * as Linking from "expo-linking";
import type { AgentRow } from "@vesta/core";
import {
  RosterHoldProvider as ProductionRosterHoldProvider,
  RosterProvider as ProductionRosterProvider,
  useRoster as useProductionRoster,
} from "../../src/session/RosterProvider";

type RosterValue = ReturnType<typeof useProductionRoster>;

const launchUrl = Linking.getLinkingURL();
const query = launchUrl === null ? {} : Linking.parse(launchUrl).queryParams;
const startsConnected = query?.visualSession === "connected";
const startsEmpty = query?.visualRoster === "empty";
const showsDashboard = query?.visualDashboard === "loaded";
const startsOffline = query?.visualReachable === "offline";
const agents: AgentRow[] = startsEmpty
  ? []
  : [
      {
        name: "aria",
        status: "alive",
        activityState: "idle",
        buildPhase: null,
        operation: null,
        startedAt: "2026-07-31T08:41:00.000Z",
        services: showsDashboard
          ? { dashboard: { port: 4310, rev: 7 } }
          : {},
      },
      {
        name: "nova",
        status: "alive",
        activityState: "thinking",
        buildPhase: null,
        operation: null,
        startedAt: "2026-07-30T16:24:00.000Z",
        services: {},
      },
      {
        name: "forge",
        status: "stopped",
        activityState: "idle",
        buildPhase: null,
        operation: null,
        startedAt: null,
        services: {},
      },
    ];
const fixture: RosterValue = {
  agents,
  agentsReady: true,
  reachable: !startsOffline,
  gatewayVersion: "0.2.0",
  gatewayChannel: "stable",
  managed: false,
  updateAvailable: false,
  latestVersion: null,
  devices: [],
};
const FixtureContext = createContext<RosterValue | null>(null);

function FixtureProvider({ children }: { children: ReactNode }) {
  return (
    <FixtureContext.Provider value={startsConnected ? fixture : null}>
      {children}
    </FixtureContext.Provider>
  );
}

export function RosterHoldProvider({ children }: { children: ReactNode }) {
  return (
    <ProductionRosterHoldProvider>{children}</ProductionRosterHoldProvider>
  );
}

export function RosterProvider({ children }: { children: ReactNode }) {
  return (
    <ProductionRosterProvider>
      <FixtureProvider>{children}</FixtureProvider>
    </ProductionRosterProvider>
  );
}

export function useRoster(): RosterValue {
  const fixtureValue = use(FixtureContext);
  const production = useProductionRoster();
  return fixtureValue ?? production;
}
