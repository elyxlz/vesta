import { useCallback, useContext, useEffect, type ReactNode } from "react";
import type { Controller, SyncState, Tree } from "@vesta/core";
import {
  checkForGatewayUpdate,
  devicesEqual,
  dismissGatewayUpdate as requestDismissUpdate,
  gatewayOperationsEqual,
  rosterFromTree,
  rostersEqual,
  selectDevices,
  selectGatewayOperation,
  triggerGatewayRestart as requestGatewayRestart,
  triggerGatewayUpdate as requestGatewayUpdate,
} from "@vesta/core";
import {
  useReplica,
  useSyncState,
  useUpdateResolution,
} from "@vesta/core/react";
import { AppBehindScreen } from "@/components/AppBehindScreen";
import { GatewayBehindScreen } from "@/components/GatewayBehindScreen";
import { useAuth } from "@/providers/AuthProvider/context";
import {
  ControllerContext,
  useControllerReconnect,
} from "@/providers/ControllerProvider/context";
import { useAgentOps } from "@/stores/use-agent-ops";
import { useRestartPending } from "@/stores/use-restart-pending";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "./context";

// Before the version gate passes, ControllerProvider renders children with no controller;
// hold the loading screen (versionChecked false) rather than flashing the connect screen.
const checkingValue: GatewayContextValue = {
  ...disconnectedValue,
  versionChecked: false,
};

function selectGateway(tree: Tree | null) {
  return tree?.gateway ?? null;
}

// The gateway-branch slice of the context value, defaulted for the not-yet-synced
// null tree in one place so the component stays under the complexity ceiling.
function gatewayValues(gateway: ReturnType<typeof selectGateway>) {
  if (gateway === null) {
    return {
      managed: false,
      gatewayChannel: "stable" as const,
      gatewayAutoUpdate: true,
      gatewayPort: 0,
      updateAvailable: false,
      latestVersion: null,
      agentsFetched: false,
      userNotificationsSeenAt: 0,
      lastUserNotificationAt: null,
    };
  }
  return {
    managed: gateway.managed,
    gatewayChannel: gateway.channel,
    gatewayAutoUpdate: gateway.autoUpdate,
    gatewayPort: gateway.port,
    updateAvailable: gateway.updateAvailable,
    latestVersion: gateway.latestVersion,
    agentsFetched: true,
    // Absent on an older gateway: treat as never caught up / empty log.
    userNotificationsSeenAt: gateway.userNotificationsSeenAt ?? 0,
    lastUserNotificationAt: gateway.lastUserNotificationAt ?? null,
  };
}

// Route compatibility screens inside the provider because their shared navbar reads gateway state.
function routeContent(syncState: SyncState, children: ReactNode): ReactNode {
  if (syncState === "app_behind") return <AppBehindScreen />;
  if (syncState === "gateway_behind") return <GatewayBehindScreen />;
  return children;
}

function ReplicaGateway({
  controller,
  children,
}: {
  controller: Controller;
  children: ReactNode;
}) {
  const gateway = useReplica(controller.replica, selectGateway);
  const gatewayOperation = useReplica(
    controller.replica,
    selectGatewayOperation,
    gatewayOperationsEqual,
  );
  const agents = useReplica(controller.replica, rosterFromTree, rostersEqual);
  const devices = useReplica(controller.replica, selectDevices, devicesEqual);
  const syncState = useSyncState(controller);
  const reconnect = useControllerReconnect();

  // The reconcile calls previously fired on every control-WS `agents` frame; they now key
  // off the replica-derived roster. Clear any "restart to apply" flag whose agent has since
  // restarted, and drop op state for agents that are gone (ends a delete's "deleting" orb).
  useEffect(() => {
    useRestartPending.getState().reconcile(agents);
    useAgentOps.getState().reconcile(agents);
  }, [agents]);

  const gatewayVersion = gateway?.version ?? "";
  const updatedTo = useUpdateResolution(gatewayOperation, gatewayVersion);

  // An update no longer ends the socket the moment it is asked for: vestad accepts it and reports
  // its phases on /sync, and the live socket reconnects on its own through the restart phase.
  const triggerGatewayUpdate = useCallback(
    () => requestGatewayUpdate(controller.http),
    [controller],
  );

  const dismissUpdate = useCallback(
    () => requestDismissUpdate(controller.http),
    [controller],
  );

  const triggerGatewayRestart = useCallback(async (): Promise<boolean> => {
    const ok = await requestGatewayRestart(controller.http);
    // A restart drops the gateway just like an update; re-attach the same way.
    if (ok) reconnect();
    return ok;
  }, [controller, reconnect]);

  const checkForUpdate = useCallback(async (): Promise<void> => {
    try {
      await checkForGatewayUpdate(controller.http);
    } catch (err) {
      console.warn("[gateway] update check request failed:", err);
    }
    // The refreshed update info flows back as a gateway `state` delta into the replica.
  }, [controller]);

  const value: GatewayContextValue = {
    ...gatewayValues(gateway),
    reachable: syncState === "open",
    gatewayVersion,
    versionChecked: true,
    gatewayOperation,
    updatedTo,
    agents,
    devices,
    triggerGatewayUpdate,
    triggerGatewayRestart,
    dismissUpdate,
    checkForUpdate,
  };

  return (
    <GatewayContext.Provider value={value}>
      {routeContent(syncState, children)}
    </GatewayContext.Provider>
  );
}

// Tolerates the ControllerProvider "checking" phase: the controller context is null until the
// version gate passes and the controller builds, so read it nullable (not useController()).
function ConnectedGateway({ children }: { children: ReactNode }) {
  const controller = useContext(ControllerContext);
  if (!controller) {
    return (
      <GatewayContext.Provider value={checkingValue}>
        {children}
      </GatewayContext.Provider>
    );
  }
  return <ReplicaGateway controller={controller}>{children}</ReplicaGateway>;
}

export function GatewayProvider({ children }: { children: ReactNode }) {
  const { connected, initialized } = useAuth();

  if (initialized && connected) {
    return <ConnectedGateway>{children}</ConnectedGateway>;
  }

  return (
    <GatewayContext.Provider value={disconnectedValue}>
      {children}
    </GatewayContext.Provider>
  );
}
