import { useCallback, useEffect, useState, type ReactNode } from "react";
import { createController, type Controller } from "@vesta/core";
import { useSyncState } from "@vesta/core/react";
import { getConnection, isTokenExpiringSoon } from "@/lib/connection";
import { ensureFreshToken } from "@/lib/token-refresh";
import { useAuth } from "@/providers/AuthProvider";
import { AppBehindScreen } from "@/components/AppBehindScreen";
import { GatewayBehindScreen } from "@/components/GatewayBehindScreen";
import { DisconnectedOverlay } from "@/components/DisconnectedOverlay";
import { createBrowserSocket } from "./browser-socket";
import { ControllerContext, ControllerReconnectContext } from "./context";

export {
  ControllerContext,
  useController,
  useControllerReconnect,
} from "./context";
export { useSyncState };

// Brief grace before the disconnect overlay appears, so quick socket blips don't flash it.
const DISCONNECT_GRACE_MS = 750;
const REAUTH_POLL_MS = 60000;

function syncUrl(): string {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vesta gateway");
  const base = conn.url.replace(/^http/, "ws");
  return `${base}/sync?token=${encodeURIComponent(conn.accessToken)}`;
}

function buildController(): Controller {
  return createController({
    sync: {
      buildUrl: syncUrl,
      createSocket: createBrowserSocket,
      setTimer: (fn, ms) => window.setTimeout(fn, ms),
      clearTimer: (handle) => window.clearTimeout(handle),
      clientVersion: __APP_VERSION__,
    },
    http: {
      baseUrl: () => getConnection()?.url ?? "",
      fetch: (input, init) => fetch(input, init),
      token: () => getConnection()?.accessToken ?? null,
      refresh: async () => (await ensureFreshToken(true)) === "ok",
    },
  });
}

// `reconnect` bumps `connectEpoch`, remounting the session with a fresh controller (the
// gateway-update path forces a reconnect this way).
function ActiveController({ children }: { children: ReactNode }) {
  const [connectEpoch, setConnectEpoch] = useState(0);
  const reconnect = useCallback(
    () => setConnectEpoch((epoch) => epoch + 1),
    [],
  );

  return (
    <ControllerReconnectContext.Provider value={reconnect}>
      <ControllerSession key={connectEpoch}>{children}</ControllerSession>
    </ControllerReconnectContext.Provider>
  );
}

// The two blocking sync states take over the whole app in place of children; every other
// state renders the app (a transient disconnect shows the overlay on top instead).
function routeTakeover(syncState: string): ReactNode {
  if (syncState === "app_behind") return <AppBehindScreen />;
  if (syncState === "gateway_behind") return <GatewayBehindScreen />;
  return null;
}

// One live controller for the lifetime of a session mount. Built once via a lazy useState
// initializer (run exactly once per mount and never discarded, so it avoids the
// useMemo-side-effect-in-render caveat), closed on unmount. Reauth rotates the socket's token
// in-band before it expires; the overlay tracks the sync sub-store. Like mobile, the desktop
// app is a drifting client: it opens /sync and the served version window (min_supported..version)
// decides compatibility. A client below the window takes over with AppBehindScreen (the app must
// update); a client ahead of the gateway takes over with GatewayBehindScreen.
function ControllerSession({ children }: { children: ReactNode }) {
  const [controller] = useState(buildController);
  const syncState = useSyncState(controller);
  const [showDisconnected, setShowDisconnected] = useState(false);

  useEffect(() => {
    return () => {
      controller.close();
    };
  }, [controller]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          if (isTokenExpiringSoon() && (await ensureFreshToken()) === "ok") {
            const conn = getConnection();
            if (conn) controller.reauth(conn.accessToken);
          }
        } catch (err) {
          console.warn("[controller] reauth failed:", err);
        }
      })();
    }, REAUTH_POLL_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [controller]);

  useEffect(() => {
    if (syncState !== "connecting" && syncState !== "reconnecting") {
      setShowDisconnected(false);
      return;
    }
    const timer = window.setTimeout(
      () => setShowDisconnected(true),
      DISCONNECT_GRACE_MS,
    );
    return () => {
      window.clearTimeout(timer);
    };
  }, [syncState]);

  return (
    <ControllerContext.Provider value={controller}>
      {routeTakeover(syncState) ?? children}
      {showDisconnected && <DisconnectedOverlay />}
    </ControllerContext.Provider>
  );
}

export function ControllerProvider({ children }: { children: ReactNode }) {
  const { initialized, connected } = useAuth();

  // Only the connected app has a gateway to talk to. Before connect, render children
  // without a controller: GatewayProvider keeps its own disconnected split for the
  // connect screen, and no consumer reads useController() until then.
  if (initialized && connected) {
    return <ActiveController>{children}</ActiveController>;
  }
  return <>{children}</>;
}
