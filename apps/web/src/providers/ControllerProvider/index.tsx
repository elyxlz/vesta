import { useCallback, useEffect, useState, type ReactNode } from "react";
import { createController, type Controller } from "@vesta/core";
import { useSyncState } from "@vesta/core/react";
import { getConnection } from "@/lib/connection";
import { websocketUrl } from "@/lib/authed-url";
import { ensureFreshToken } from "@/lib/token-refresh";
import { useAuth } from "@/providers/AuthProvider";
import { DisconnectedOverlay } from "@/components/DisconnectedOverlay";
import { createBrowserSocket } from "./browser-socket";
import { runReauthCheck } from "./reauth-poll";
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

function buildController(): Controller {
  return createController({
    sync: {
      buildUrl: () => websocketUrl("/sync"),
      createSocket: createBrowserSocket,
      setTimer: (fn, ms) => window.setTimeout(fn, ms),
      clearTimer: (handle) => window.clearTimeout(handle),
      clientVersion: __CLIENT_VERSION__,
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

// One live controller for the lifetime of a session mount. Built once via a lazy useState
// initializer (run exactly once per mount and never discarded, so it avoids the
// useMemo-side-effect-in-render caveat), closed on unmount. Reauth rotates the socket's token
// in-band before it expires; the overlay tracks the sync sub-store. Like mobile, the desktop
// app is a drifting client: it opens /sync and the served version window (min_supported..version)
// decides compatibility. GatewayProvider turns incompatible states into blocking screens while
// keeping the gateway context mounted for their shared UI.
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
    // Also on mount, not just every poll: a session restored with an already-expired token
    // would otherwise keep retrying /sync with it for a whole interval.
    const tick = () => {
      void runReauthCheck((token) => {
        controller.reauth(token);
      }).catch((err: unknown) =>
        console.warn("[controller] reauth failed:", err),
      );
    };
    tick();
    const timer = window.setInterval(tick, REAUTH_POLL_MS);
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
      {children}
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
