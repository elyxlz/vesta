import { createContext, useContext } from "react";
import type { DeviceInfo, GatewayOperation, ReleaseChannel } from "@vesta/core";
import type { AgentRow } from "@/lib/types";

export interface GatewayContextValue {
  reachable: boolean;
  /** True iff this is a hosted (vesta.run-managed) gateway; gates the account link. */
  managed: boolean;
  gatewayVersion: string;
  gatewayChannel: ReleaseChannel;
  gatewayAutoUpdate: boolean;
  gatewayPort: number;
  versionChecked: boolean;
  updateAvailable: boolean;
  latestVersion: string | null;
  /** The gateway operation in flight (an update or a restart), null while the gateway is idle.
   * Locks the app to home. */
  gatewayOperation: GatewayOperation | null;
  /** The version an update just landed on, held briefly after the operation clears. */
  updatedTo: string | null;
  agents: AgentRow[];
  agentsFetched: boolean;
  devices: DeviceInfo[];
  /** The user-notification feed's synced seen watermark, 0 before the first catch-up ever. */
  userNotificationsSeenAt: number;
  /** The newest feed entry's stamp, null on an empty log or an older gateway. */
  lastUserNotificationAt: number | null;
  triggerGatewayUpdate: () => Promise<boolean>;
  triggerGatewayRestart: () => Promise<boolean>;
  dismissUpdate: () => Promise<boolean>;
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
  gatewayOperation: null,
  updatedTo: null,
  agents: [],
  agentsFetched: false,
  devices: [],
  userNotificationsSeenAt: 0,
  lastUserNotificationAt: null,
  triggerGatewayUpdate: () => Promise.resolve(false),
  triggerGatewayRestart: () => Promise.resolve(false),
  dismissUpdate: () => Promise.resolve(false),
  checkForUpdate: () => Promise.resolve(),
};

export function useGateway() {
  const context = useContext(GatewayContext);
  if (!context) {
    throw new Error("useGateway must be used within GatewayProvider");
  }
  return context;
}
