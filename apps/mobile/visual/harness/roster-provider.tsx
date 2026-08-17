import { createContext, use, type ReactNode } from "react";
import * as Linking from "expo-linking";
import type { AgentRow, DeviceInfo } from "@vesta/core";
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
const startsLoading = query?.visualRoster === "loading";
const showsDashboard = query?.visualDashboard === "loaded";
const startsOffline = query?.visualReachable === "offline";
const hasGatewayUpdate = query?.visualGatewayUpdate === "available";
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
const devices: DeviceInfo[] = [
  {
    id: "visual-phone",
    kind: "mobile",
    descriptor: "iPhone 17",
    present: true,
    lastSeen: "2026-08-01T09:20:00.000Z",
    pushEnabled: true,
    location: "Lisbon, Portugal",
    timezone: "Europe/Lisbon",
    position: null,
    positionAt: null,
  },
  {
    id: "visual-web",
    kind: "web",
    descriptor: "Safari on Mac",
    present: false,
    lastSeen: "2026-07-30T18:05:00.000Z",
    pushEnabled: false,
    location: null,
    timezone: null,
    position: null,
    positionAt: null,
  },
];
const fixture: RosterValue = {
  agents: startsLoading ? [] : agents,
  agentsReady: !startsLoading,
  reachable: !startsOffline,
  gatewayVersion: "0.2.0",
  gatewayChannel: "stable",
  managed: false,
  updateAvailable: hasGatewayUpdate,
  latestVersion: hasGatewayUpdate ? "0.2.1" : null,
  devices,
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
