import { useCallback, useContext, useEffect, type ReactNode } from "react";
import type { Controller, Tree } from "@vesta/core";
import { useReplica, useSyncState } from "@vesta/core/react";
import { apiFetch } from "@/api/client";
import { useAuth } from "@/providers/AuthProvider";
import {
  ControllerContext,
  useControllerReconnect,
} from "@/providers/ControllerProvider";
import type { ServiceInfo } from "@vesta/core";
import type { AgentRow } from "@/lib/types";
import { useAgentOps } from "@/stores/use-agent-ops";
import { useRestartPending } from "@/stores/use-restart-pending";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "./context";

export { useGateway } from "./context";

// A manual check fetches from GitHub server-side, so allow longer than the
// cached /version read (vestad's own fetch timeout is 10s).
const VERSION_CHECK_TIMEOUT_MS = 15000;

// Before the version gate passes, ControllerProvider renders children with no controller;
// hold the loading screen (versionChecked false) rather than flashing the connect screen.
const checkingValue: GatewayContextValue = {
  ...disconnectedValue,
  versionChecked: false,
};

function servicesEqual(
  a: Record<string, ServiceInfo>,
  b: Record<string, ServiceInfo>,
): boolean {
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every(
    (key) => a[key]?.port === b[key]?.port && a[key]?.rev === b[key]?.rev,
  );
}

// Structural compare of the derived roster so an unrelated tree delta (e.g. a notification)
// does not hand every gateway consumer a fresh array.
function agentRowsEqual(a: AgentRow[], b: AgentRow[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((row, index) => {
    const other = b[index];
    if (other === undefined) return false;
    return (
      row.name === other.name &&
      row.status === other.status &&
      row.activityState === other.activityState &&
      row.buildPhase === other.buildPhase &&
      row.startedAt === other.startedAt &&
      servicesEqual(row.services, other.services)
    );
  });
}

function selectAgents(tree: Tree | null): AgentRow[] {
  if (!tree) return [];
  return Object.entries(tree.agents).map(([name, node]) => ({
    name,
    ...node.info,
  }));
}

function selectGateway(tree: Tree | null) {
  return tree?.gateway ?? null;
}

function ReplicaGateway({
  controller,
  children,
}: {
  controller: Controller;
  children: ReactNode;
}) {
  const gateway = useReplica(controller.replica, selectGateway);
  const agents = useReplica(controller.replica, selectAgents, agentRowsEqual);
  const syncState = useSyncState(controller);
  const reconnect = useControllerReconnect();

  // The reconcile calls previously fired on every control-WS `agents` frame; they now key
  // off the replica-derived roster. Clear any "restart to apply" flag whose agent has since
  // restarted, and drop op state for agents that are gone (ends a delete's "deleting" orb).
  useEffect(() => {
    useRestartPending.getState().reconcile(agents);
    useAgentOps.getState().reconcile(agents);
  }, [agents]);

  const triggerGatewayUpdate = useCallback(async (): Promise<boolean> => {
    try {
      await apiFetch("/gateway/update", { method: "POST" });
    } catch (err) {
      console.warn("[gateway] update request failed:", err);
      return false;
    }
    // Force a fresh controller/socket so the app re-attaches to the restarting gateway.
    reconnect();
    return true;
  }, [reconnect]);

  const checkForUpdate = useCallback(async (): Promise<void> => {
    try {
      await apiFetch("/version/check", {
        method: "POST",
        signal: AbortSignal.timeout(VERSION_CHECK_TIMEOUT_MS),
      });
    } catch (err) {
      console.warn("[gateway] update check request failed:", err);
    }
    // The refreshed update info flows back as a gateway `state` delta into the replica.
  }, []);

  const value: GatewayContextValue = {
    reachable: syncState === "open",
    managed: gateway?.managed ?? false,
    gatewayVersion: gateway?.version ?? "",
    gatewayChannel: gateway?.channel ?? "stable",
    gatewayAutoUpdate: gateway?.autoUpdate ?? true,
    gatewayPort: gateway?.port ?? 0,
    versionChecked: true,
    updateAvailable: gateway?.updateAvailable ?? false,
    latestVersion: gateway?.latestVersion ?? null,
    agents,
    agentsFetched: gateway !== null,
    triggerGatewayUpdate,
    checkForUpdate,
  };

  return (
    <GatewayContext.Provider value={value}>{children}</GatewayContext.Provider>
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
