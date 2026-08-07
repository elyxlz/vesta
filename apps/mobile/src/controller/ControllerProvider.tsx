import { useEffect, useState, type ReactNode } from "react";
import Constants from "expo-constants";
import { resolveClientVersion, type Controller } from "@vesta/core";
import { useSyncState } from "@vesta/core/react";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import { buildController } from "./build-controller";
import { deviceIdentity } from "./device-identity";
import { controllerGateAction, type GateInput } from "./controller-gate";
import { ControllerContext } from "./context";
import { createAppStateForegroundSignal } from "./foreground-signal";
import { useOptionalControllerSyncState } from "./optional-controller-store";
import { runReauthCheck } from "./reauth-poll";
import { AppBehindScreen } from "./AppBehindScreen";
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

// Owns the single sync controller's lifetime. The pure gate (controller-gate) decides build
// vs. close from (connected, foreground); AppState drives foreground. The build effect keys on
// the gateway identity (connectionKeyOf), not the connection object: a token rotation preserves
// the key and reauths in-band (the reauth poll below), only a gateway switch rebuilds.
// Backgrounding closes the socket; returning to foreground builds a new epoch.
function ConnectedController({ children }: { children: ReactNode }) {
  const { connection, api, refreshAccessToken } = useSession();
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

  return (
    <ControllerContext.Provider value={controller}>
      {syncState === "app_behind" ? (
        <AppBehindScreen />
      ) : (
        <GatewayUpdateGate blocked={syncState === "gateway_behind"}>
          {children}
        </GatewayUpdateGate>
      )}
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
