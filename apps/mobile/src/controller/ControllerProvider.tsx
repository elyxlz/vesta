import { useEffect, useMemo, useState, type ReactNode } from "react";
import Constants from "expo-constants";
import { useRouter, useSegments } from "expo-router";
import {
  gatewayOperationsEqual,
  resolveClientVersion,
  selectGatewayOperation,
  type Controller,
  type Tree,
} from "@vesta/core";
import { useSyncState, useUpdateResolution } from "@vesta/core/react";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import { buildController } from "./build-controller";
import { deviceIdentity } from "./device-identity";
import { controllerGateAction, type GateInput } from "./controller-gate";
import { ControllerContext } from "./context";
import { createAppStateForegroundSignal } from "./foreground-signal";
import {
  useOptionalControllerReplica,
  useOptionalControllerSyncState,
} from "./optional-controller-store";
import { runReauthCheck } from "./reauth-poll";
import { AppBehindScreen } from "./AppBehindScreen";
import { GatewayOperationContext } from "./gateway-operation-context";
import { gatewayOperationRouteAction } from "./gateway-operation-route-model";
import { GatewayUpdateGate } from "./gateway-update-gate";

// Development variants drift with source rather than releases, so they deliberately fail open.
// Production variants compare their release against the gateway's compatibility window.
const CLIENT_VERSION = resolveClientVersion(
  Constants.expoConfig?.version,
  Constants.expoConfig?.extra?.appVariant === "development",
);

export { useController } from "./context";
export { useSyncState };

const REAUTH_POLL_MS = 60000;

// Module scope keeps the selector identity stable across renders, which the replica store memo needs.
const selectGatewayVersion = (tree: Tree | null) => tree?.gateway.version ?? "";

// Owns the single sync controller's lifetime. The pure gate (controller-gate) decides build
// vs. close from (connected, foreground); AppState drives foreground. The build effect keys on
// the gateway identity (connectionKeyOf), not the connection object: a token rotation preserves
// the key and reauths in-band (the reauth poll below), only a gateway switch rebuilds.
// Backgrounding closes the socket; returning to foreground builds a new epoch.
function ConnectedController({ children }: { children: ReactNode }) {
  const { connection, api, refreshAccessToken } = useSession();
  const router = useRouter();
  const segments = useSegments();
  const [signal] = useState(createAppStateForegroundSignal);
  const [controller, setController] = useState<Controller | null>(null);
  const [device, setDevice] = useState<{ id: string; descriptor: string } | undefined>(undefined);
  const connectionKey = connectionKeyOf(connection);

  // Resolve this device's identity once (the id lives in AsyncStorage). When it lands it enters the
  // build effect's deps, rebuilding the controller so /sync reports the device.
  useEffect(() => {
    let active = true;
    void deviceIdentity().then((resolved) => {
      if (active) setDevice(resolved);
    });
    return () => {
      active = false;
    };
  }, []);
  const syncState = useOptionalControllerSyncState(controller);
  // Behind-ness is latched across the reconnect gap: every socket close flips syncState to
  // "reconnecting" and only an accepted hello reaches "open", so the update sheet neither pops
  // out on a transient blip nor flashes home mid-update. Derived during render (the previous
  // render's latch is the carried state); a gateway switch starts unlatched.
  const [behindLatch, setBehindLatch] = useState({
    key: connectionKey,
    behind: false,
  });
  const gatewayBehind =
    syncState === "gateway_behind" ||
    (behindLatch.key === connectionKey &&
      syncState !== "open" &&
      behindLatch.behind);
  if (behindLatch.key !== connectionKey || behindLatch.behind !== gatewayBehind) {
    setBehindLatch({ key: connectionKey, behind: gatewayBehind });
  }
  // A gateway update takes the app back to home for as long as it runs: every agent may be
  // mid-backup and the gateway is about to restart, so home renders the update and only settings
  // stays reachable beside it.
  const updateOperation = useOptionalControllerReplica(
    controller,
    selectGatewayOperation,
    gatewayOperationsEqual,
  );
  const gatewayVersion = useOptionalControllerReplica(
    controller,
    selectGatewayVersion,
  );
  // The other half of the same story: once the operation clears against a new version, home says so
  // for a moment. A client that sees this is one the gateway never has to notify.
  const updatedTo = useUpdateResolution(updateOperation, gatewayVersion);
  const operationState = useMemo(
    () => ({ operation: updateOperation, updatedTo }),
    [updateOperation, updatedTo],
  );
  const routeAction = gatewayOperationRouteAction({
    operating: updateOperation !== null,
    activeRoute: segments[0] as string | undefined,
  });

  useEffect(() => {
    let prev: GateInput = { connected: false, foreground: false };
    let current: Controller | null = null;
    const reconcile = (foreground: boolean) => {
      const next: GateInput = { connected: connectionKey !== null, foreground };
      const action = controllerGateAction(prev, next);
      prev = next;
      if (action === "build") {
        current = buildController(
          {
            getConnection: api.getConnection,
            refreshAccessToken,
            websocketUrl: api.websocketUrl,
          },
          CLIENT_VERSION,
          device,
        );
        setController(current);
      } else if (action === "close") {
        current?.close();
        current = null;
        setController(null);
      }
    };
    reconcile(signal.isForeground());
    const unsubscribe = signal.subscribe(reconcile);
    return () => {
      unsubscribe();
      current?.close();
      setController(null);
    };
  }, [connectionKey, api, refreshAccessToken, signal, device]);

  useEffect(() => {
    if (!controller) return;
    // Also on mount, not just every poll: a session restored (or returned to the foreground)
    // with an already-expired token would otherwise keep retrying /sync with it for a whole
    // interval.
    const tick = () => {
      void runReauthCheck({
        getConnection: api.getConnection,
        refreshAccessToken,
        reauth: (token) => {
          controller.reauth(token);
        },
      }).catch((err: unknown) =>
        console.warn("[controller] reauth failed:", err),
      );
    };
    tick();
    const timer = setInterval(tick, REAUTH_POLL_MS);
    return () => {
      clearInterval(timer);
    };
  }, [controller, api, refreshAccessToken]);

  useEffect(() => {
    if (routeAction === "none") return;
    router.dismissTo("/");
  }, [routeAction, router]);

  return (
    <ControllerContext.Provider value={controller}>
      <GatewayOperationContext.Provider value={operationState}>
        {syncState === "app_behind" ? (
          <AppBehindScreen />
        ) : (
          <GatewayUpdateGate blocked={gatewayBehind}>
            {children}
          </GatewayUpdateGate>
        )}
      </GatewayOperationContext.Provider>
    </ControllerContext.Provider>
  );
}

// Before connect (and on the connect screens) there is no gateway to talk to: render children
// with a null context, mirroring web's not-connected passthrough. No consumer reads the
// controller until the app is connected.
export function ControllerProvider({ children }: { children: ReactNode }) {
  const { status } = useSession();
  if (status !== "connected") {
    return (
      <ControllerContext.Provider value={null}>
        {children}
      </ControllerContext.Provider>
    );
  }
  return <ConnectedController>{children}</ConnectedController>;
}
