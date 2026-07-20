import { useCallback, useEffect, useState, type ReactNode } from "react";
import { createController, type Controller } from "@vesta/core";
import { useSyncState } from "@vesta/core/react";
import { getConnection, isTokenExpiringSoon } from "@/lib/connection";
import { ensureFreshToken } from "@/lib/token-refresh";
import { fetchVersionInfo } from "@/api/gateway";
import { useAuth } from "@/providers/AuthProvider";
import { VersionMismatchScreen } from "@/components/VersionMismatchScreen";
import { DisconnectedOverlay } from "@/components/DisconnectedOverlay";
import { createBrowserSocket } from "./browser-socket";
import { ControllerContext, ControllerReconnectContext } from "./context";

export {
  ControllerContext,
  useController,
  useControllerReconnect,
} from "./context";
export { useSyncState };

// Brief grace before the disconnect overlay appears, so quick socket blips and the
// gap between the version gate and the first socket open don't flash it.
const DISCONNECT_GRACE_MS = 750;
const REAUTH_POLL_MS = 60000;

type GateState = "checking" | "ready" | "mismatch";

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
    },
    http: {
      baseUrl: () => getConnection()?.url ?? "",
      fetch: (input, init) => fetch(input, init),
      token: () => getConnection()?.accessToken ?? null,
      refresh: async () => (await ensureFreshToken(true)) === "ok",
    },
  });
}

// The controller (and its socket) is constructed only once the version gate passes, so a
// mismatch never opens a socket. `reconnect` bumps `connectEpoch`, remounting the session with
// a fresh controller (the gateway-update path forces a reconnect this way).
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

// One live controller for the lifetime of a session mount. Built once via a lazy useState
// initializer (run exactly once per mount and never discarded, so it avoids the
// useMemo-side-effect-in-render caveat), closed on unmount. Reauth rotates the socket's token
// in-band before it expires; the overlay tracks the sync sub-store.
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
    if (syncState === "open") {
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
      {children}
      {showDisconnected && <DisconnectedOverlay />}
    </ControllerContext.Provider>
  );
}

// Pre-connect gate: refresh the token (bail to the connect screen on a dead session) and
// fetch the gateway version over HTTP before any socket opens. On a version mismatch the
// whole app is replaced by VersionMismatchScreen and no controller is built.
function ConnectedController({ children }: { children: ReactNode }) {
  const { expireSession } = useAuth();
  const [gate, setGate] = useState<GateState>("checking");
  const [gatewayVersion, setGatewayVersion] = useState("");

  useEffect(() => {
    let cancelled = false;
    const runGate = async (): Promise<void> => {
      if ((await ensureFreshToken()) === "expired") {
        if (!cancelled) expireSession();
        return;
      }
      const data = await fetchVersionInfo();
      if (cancelled) return;
      if (data?.version) {
        setGatewayVersion(data.version);
        if (data.version !== __APP_VERSION__) {
          setGate("mismatch");
          return;
        }
      }
      setGate("ready");
    };
    void runGate();
    return () => {
      cancelled = true;
    };
  }, [expireSession]);

  if (gate === "mismatch") {
    return <VersionMismatchScreen gatewayVersion={gatewayVersion} />;
  }
  if (gate === "ready") {
    return <ActiveController>{children}</ActiveController>;
  }
  return <>{children}</>;
}

export function ControllerProvider({ children }: { children: ReactNode }) {
  const { initialized, connected } = useAuth();

  // Only the connected app has a gateway to talk to. Before connect, render children
  // without a controller: GatewayProvider keeps its own disconnected split for the
  // connect screen, and no consumer reads useController() until then.
  if (initialized && connected) {
    return <ConnectedController>{children}</ConnectedController>;
  }
  return <>{children}</>;
}
