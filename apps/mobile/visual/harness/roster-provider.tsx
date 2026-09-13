import { createContext, use, type ReactNode } from "react";
import { directRoomId } from "@vesta/core";
import type {
  AgentOperation,
  AgentRow,
  AgentStatus,
  DeviceInfo,
  Room,
} from "@vesta/core";
import { visualSwitch } from "./launch-query";
import {
  RosterHoldProvider as ProductionRosterHoldProvider,
  RosterProvider as ProductionRosterProvider,
  useRoster as useProductionRoster,
} from "../../src/session/RosterProvider";

type RosterValue = ReturnType<typeof useProductionRoster>;

const startsConnected = visualSwitch("visualSession") === "connected";
const startsEmpty = visualSwitch("visualRoster") === "empty";
const startsLoading = visualSwitch("visualRoster") === "loading";
const showsDashboard = visualSwitch("visualDashboard") !== null;
// visualServices=voice registers a voice service on aria, which is what puts
// the microphone in the chat composer.
const hasVoiceService = visualSwitch("visualServices") === "voice";
const startsOffline = visualSwitch("visualReachable") === "offline";
const hasGatewayUpdate = visualSwitch("visualGatewayUpdate") === "available";
const managed = visualSwitch("visualManaged") === "true";
const devicesVariant = visualSwitch("visualDevices");

// visualAgent puts aria, the first carousel page, into one status (or one
// operation, or booting), so each agent state is its own launch with no swipe.
const AGENT_STATUSES: readonly AgentStatus[] = [
  "alive",
  "starting",
  "setting_up",
  "not_authenticated",
  "unprovisioned",
  "restarting",
  "rebuilding",
  "stopped",
  "dead",
  "not_found",
];
const AGENT_OPERATIONS: readonly AgentOperation[] = ["backing_up", "restoring"];
const requestedAgent = visualSwitch("visualAgent");
const ariaStatus = AGENT_STATUSES.find((status) => status === requestedAgent);
const ariaOperation = AGENT_OPERATIONS.find(
  (operation) => operation === requestedAgent,
);
const ariaBooting = requestedAgent === "booting";
const ariaThinking = requestedAgent === "thinking";
const aria: AgentRow = {
  name: "aria",
  status: ariaStatus ?? "alive",
  activityState: ariaThinking ? "thinking" : "idle",
  buildPhase: ariaStatus === "starting" ? "starting" : null,
  operation: ariaOperation ?? null,
  booting: ariaBooting,
  startedAt:
    (ariaStatus ?? "alive") === "alive" ? "2026-07-31T08:41:00.000Z" : null,
  services: {
    ...(showsDashboard
      ? { dashboard: { port: 4310, rev: 7, public: false } }
      : {}),
    ...(hasVoiceService
      ? { voice: { port: 4320, rev: 2, public: false } }
      : {}),
  },
};
export const fixtureAgents: AgentRow[] = startsEmpty
  ? []
  : [
      aria,
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
const phonePosition = {
  latitude: 38.7223,
  longitude: -9.1393,
  accuracyM: 25,
  place: { city: "Lisbon", region: "Lisboa", country: "Portugal" },
};
const allDevices: DeviceInfo[] = [
  {
    id: "visual-phone",
    kind: "mobile",
    descriptor: "iPhone 17",
    present: true,
    lastSeen: "2026-08-01T09:20:00.000Z",
    pushEnabled: true,
    timezone: "Europe/Lisbon",
    position: devicesVariant === "position" ? phonePosition : null,
    positionAt:
      devicesVariant === "position" ? "2026-08-01T09:19:00.000Z" : null,
  },
  {
    id: "visual-web",
    kind: "web",
    descriptor: "Safari on Mac",
    present: false,
    lastSeen: "2026-07-30T18:05:00.000Z",
    pushEnabled: false,
    timezone: null,
    position: null,
    positionAt: null,
  },
];
export const fixtureDevices = devicesVariant === "none" ? [] : allDevices;
// Every fixture agent has its own direct room, so the chat scenarios open the conversation the
// app actually reads. visualRooms=group adds a group the Chats list and the room screen render.
export const GROUP_ROOM_ID = "grp-launch";
const groupRoom: Room = {
  id: GROUP_ROOM_ID,
  name: "Launch week",
  agents: ["aria", "nova"],
  createdAt: 1_754_000_000,
  lastMessageAt: 1_754_038_800,
};
const fixtureRooms: Room[] = [
  ...(visualSwitch("visualRooms") === "group" ? [groupRoom] : []),
  ...fixtureAgents.map((agent, index) => ({
    id: directRoomId(agent.name),
    name: null,
    agents: [agent.name],
    createdAt: 1_753_900_000,
    lastMessageAt: 1_754_038_000 - index * 3_600,
  })),
];
const fixture: RosterValue = {
  agents: startsLoading ? [] : fixtureAgents,
  agentsReady: !startsLoading,
  reachable: !startsOffline,
  gatewayVersion: "0.2.0",
  gatewayChannel: visualSwitch("visualChannel") === "beta" ? "beta" : "stable",
  managed,
  updateAvailable: hasGatewayUpdate,
  latestVersion: hasGatewayUpdate ? "0.2.1" : null,
  devices: fixtureDevices,
  rooms: startsLoading ? [] : fixtureRooms,
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
