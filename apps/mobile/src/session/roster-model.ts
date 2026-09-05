import type { AgentRow, ReleaseChannel, Room } from "@vesta/core";

export interface RosterSnapshot {
  agents: AgentRow[];
  rooms: Room[];
  gatewayVersion: string;
  gatewayChannel: ReleaseChannel;
  managed: boolean;
  updateAvailable: boolean;
  latestVersion: string | null;
}

export interface RosterHold {
  connectionKey: string;
  agents: AgentRow[];
  // Held beside the agents: the room screen resolves its id off this list, so a controller epoch
  // must not read as a node with no conversations.
  rooms: Room[];
  agentsReady: boolean;
  gatewayVersion: string | undefined;
  gatewayChannel: ReleaseChannel | undefined;
  managed: boolean;
  updateAvailable: boolean;
  latestVersion: string | null;
}

export const emptyRosterHold: RosterHold = {
  connectionKey: "",
  agents: [],
  rooms: [],
  agentsReady: false,
  gatewayVersion: undefined,
  gatewayChannel: undefined,
  managed: false,
  updateAvailable: false,
  latestVersion: null,
};

// Stale-while-reconnecting hold. A fresh snapshot (the summary tree has arrived) becomes the new
// hold; while none is available (reconnecting, or the controller is torn down on background) the
// last-known hold for THIS gateway is retained so the roster never blanks. A changed connectionKey
// drops the prior gateway's roster so its agents never bleed onto the next gateway.
export function reconcileRosterHold(
  prev: RosterHold,
  connectionKey: string,
  fresh: RosterSnapshot | null,
): RosterHold {
  const base = connectionKey === prev.connectionKey ? prev : emptyRosterHold;
  if (!fresh) return { ...base, connectionKey };
  return {
    connectionKey,
    agents: fresh.agents,
    rooms: fresh.rooms,
    agentsReady: true,
    gatewayVersion: fresh.gatewayVersion,
    gatewayChannel: fresh.gatewayChannel,
    managed: fresh.managed,
    updateAvailable: fresh.updateAvailable,
    latestVersion: fresh.latestVersion,
  };
}
