import type { AgentRow } from "@vesta/core";

export interface RosterSnapshot {
  agents: AgentRow[];
  gatewayVersion: string;
  managed: boolean;
  updateAvailable: boolean;
  latestVersion: string | null;
}

export interface RosterHold {
  connectionKey: string;
  agents: AgentRow[];
  agentsReady: boolean;
  gatewayVersion: string | undefined;
  managed: boolean;
  updateAvailable: boolean;
  latestVersion: string | null;
}

export const emptyRosterHold: RosterHold = {
  connectionKey: "",
  agents: [],
  agentsReady: false,
  gatewayVersion: undefined,
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
    agentsReady: true,
    gatewayVersion: fresh.gatewayVersion,
    managed: fresh.managed,
    updateAvailable: fresh.updateAvailable,
    latestVersion: fresh.latestVersion,
  };
}
