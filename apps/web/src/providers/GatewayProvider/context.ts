import { createContext, useContext } from "react";
import type { ReleaseChannel } from "@vesta/core";
import type { AgentRow } from "@/lib/types";

// Context + hook live here, separate from the GatewayProvider component, so the
// GatewayContext identity is stable across Fast Refresh. Co-locating them with the
// component made every edit re-create the context, detaching mounted consumers
// ("useGateway must be used within GatewayProvider" on hot reload).
export interface GatewayContextValue {
  reachable: boolean;
  /** True iff this is a hosted (vesta.run-managed) box — gates the account link. */
  managed: boolean;
  gatewayVersion: string;
  gatewayChannel: ReleaseChannel;
  gatewayAutoUpdate: boolean;
  gatewayPort: number;
  versionChecked: boolean;
  updateAvailable: boolean;
  latestVersion: string | null;
  agents: AgentRow[];
  agentsFetched: boolean;
  triggerGatewayUpdate: () => Promise<boolean>;
  triggerGatewayRestart: () => Promise<boolean>;
  checkForUpdate: () => Promise<void>;
}

export const GatewayContext = createContext<GatewayContextValue | null>(null);

export const disconnectedValue: GatewayContextValue = {
  reachable: false,
  managed: false,
  gatewayVersion: "",
  gatewayChannel: "stable",
  gatewayAutoUpdate: true,
  gatewayPort: 0,
  versionChecked: true,
  updateAvailable: false,
  latestVersion: null,
  agents: [],
  agentsFetched: false,
  triggerGatewayUpdate: () => Promise.resolve(false),
  triggerGatewayRestart: () => Promise.resolve(false),
  checkForUpdate: () => Promise.resolve(),
};

export function useGateway() {
  const context = useContext(GatewayContext);
  if (!context) {
    throw new Error("useGateway must be used within GatewayProvider");
  }
  return context;
}
