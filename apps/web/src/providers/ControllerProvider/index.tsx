import {
  useCallback,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createController, type Controller } from "@vesta/core";
import { useSyncState } from "@vesta/core/react";
import { getConnection } from "@/lib/connection";
import { websocketUrl } from "@/lib/authed-url";
import { native } from "@/lib/native";
import { deviceIdentity } from "@/lib/device-identity";
import { ensureFreshToken } from "@/lib/token-refresh";
import { useAuth } from "@/providers/AuthProvider/context";
import { DisconnectedOverlay } from "@/components/DisconnectedOverlay";
import { createBrowserSocket } from "./browser-socket";
import { runReauthCheck } from "./reauth-poll";
import { ControllerContext, ControllerReconnectContext } from "./context";

// Brief grace before the disconnect overlay appears, so quick socket blips don't flash it.
const DISCONNECT_GRACE_MS = 750;
export const REAUTH_POLL_MS = 60000;

function buildController(): Controller {
  return createController({
    sync: {
      buildUrl: () => websocketUrl("/sync"),
      createSocket: createBrowserSocket,
      setTimer: (fn, ms) => window.setTimeout(fn, ms),
      clearTimer: (handle) => window.clearTimeout(handle),
      clientVersion: __CLIENT_VERSION__,
      clientKind: native.runtime === "electron" ? "desktop" : "web",
      device: deviceIdentity(),
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

// A slot whose occupant the effect owns, read through useSyncExternalStore: the controller is
// created by the effect whose cleanup closes it, so the two lifetimes cannot diverge. Fast
// Refresh and StrictMode re-run effects while preserving state, and a render-owned controller
// would be closed by the re-run's cleanup and stranded terminal (sync state "closed", which
// never reconnects); here the re-run builds a live replacement instead.
function createControllerSlot() {
  let current: Controller | null = null;
  const listeners = new Set<() => void>();
  return {
    get: () => current,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    set: (next: Controller | null) => {
      current = next;
      for (const listener of listeners) listener();
    },
  };
}

// Children wait out the one pre-effect render with no controller.
function ControllerSession({ children }: { children: ReactNode }) {
  const [slot] = useState(createControllerSlot);
  const controller = useSyncExternalStore(slot.subscribe, slot.get);

  useEffect(() => {
    const created = buildController();
    slot.set(created);
    return () => {
      created.close();
      slot.set(null);
    };
  }, [slot]);

  if (controller === null) return null;
  return <LiveSession controller={controller}>{children}</LiveSession>;
}

// Reauth rotates the socket's token in-band before it expires; the overlay tracks the sync
// sub-store. Like mobile, the desktop app is a drifting client: it opens /sync and the served
// version window (min_supported..version) decides compatibility. GatewayProvider turns
// incompatible states into blocking screens while keeping the gateway context mounted for
// their shared UI.
function LiveSession({
  controller,
  children,
}: {
  controller: Controller;
  children: ReactNode;
}) {
  const syncState = useSyncState(controller);
  const connecting = syncState === "connecting" || syncState === "reconnecting";
  // The grace timer belongs to one connecting stretch: a state change starts it over, and
  // its expiry is what shows the overlay.
  const [grace, setGrace] = useState({ state: syncState, elapsed: false });
  if (grace.state !== syncState) setGrace({ state: syncState, elapsed: false });
  const showDisconnected = connecting && grace.elapsed;

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
    if (!connecting) return;
    const timer = window.setTimeout(() => {
      setGrace({ state: syncState, elapsed: true });
    }, DISCONNECT_GRACE_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [connecting, syncState]);

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
