import { useEffect, useState, type ReactNode } from "react";
import Constants from "expo-constants";
import type { Controller } from "@vesta/core";
import { useSyncState } from "@vesta/core/react";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import { buildController } from "./build-controller";
import { controllerGateAction, type GateInput } from "./controller-gate";
import { ControllerContext } from "./context";
import { createAppStateForegroundSignal } from "./foreground-signal";
import { useOptionalControllerSyncState } from "./optional-controller-store";
import { runReauthCheck } from "./reauth-poll";
import { AppBehindScreen } from "./AppBehindScreen";
import { GatewayBehindScreen } from "./GatewayBehindScreen";

// This app's own release version, used to block running ahead of the gateway. Undefined (or
// non-semver) fails open in core, so a dev build never blocks.
const CLIENT_VERSION = Constants.expoConfig?.version ?? undefined;

export { useController } from "./context";
export { useSyncState };

const REAUTH_POLL_MS = 60000;

// Owns the single sync controller's lifetime. The pure gate (controller-gate) decides build
// vs. close from (connected, foreground); AppState drives foreground. The build effect keys on
// the gateway identity (connectionKeyOf), not the connection object: a token rotation preserves
// the key and reauths in-band (the reauth poll below), only a gateway switch rebuilds.
// Backgrounding closes the socket; returning to foreground builds a new epoch.
function ConnectedController({ children }: { children: ReactNode }) {
  const { connection, api, refreshAccessToken } = useSession();
  const [signal] = useState(createAppStateForegroundSignal);
  const [controller, setController] = useState<Controller | null>(null);
  const connectionKey = connectionKeyOf(connection);
  const syncState = useOptionalControllerSyncState(controller);

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
          },
          CLIENT_VERSION,
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
  }, [connectionKey, api, refreshAccessToken, signal]);

  useEffect(() => {
    if (!controller) return;
    const timer = setInterval(() => {
      void runReauthCheck({
        getConnection: api.getConnection,
        refreshAccessToken,
        reauth: (token) => {
          controller.reauth(token);
        },
      }).catch((err: unknown) =>
        console.warn("[controller] reauth failed:", err),
      );
    }, REAUTH_POLL_MS);
    return () => {
      clearInterval(timer);
    };
  }, [controller, api, refreshAccessToken]);

  return (
    <ControllerContext.Provider value={controller}>
      {routeTakeover(syncState) ?? children}
    </ControllerContext.Provider>
  );
}

// The two blocking sync states take over in place of the app; every other state renders it.
function routeTakeover(syncState: string): ReactNode {
  if (syncState === "app_behind") return <AppBehindScreen />;
  if (syncState === "gateway_behind") return <GatewayBehindScreen />;
  return null;
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
