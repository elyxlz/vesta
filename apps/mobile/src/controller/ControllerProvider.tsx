import { useEffect, useState, type ReactNode } from "react";
import type { Controller } from "@vesta/core";
import { useSyncState } from "@vesta/core/react";
import { useSession } from "@/session/SessionProvider";
import { buildController } from "./build-controller";
import { controllerGateAction, type GateInput } from "./controller-gate";
import { ControllerContext } from "./context";
import { createAppStateForegroundSignal } from "./foreground-signal";
import { IncompatibleScreen } from "./IncompatibleScreen";

export { useController } from "./context";
export { useSyncState };

// Owns the single sync controller's lifetime. The pure gate (controller-gate) decides build
// vs. close from (connected, foreground); AppState drives foreground, and a connection change
// (new gateway or refreshed token) re-runs the effect, closing the old controller and building
// a fresh one. Backgrounding closes the socket; returning to foreground builds a new epoch.
function ConnectedController({ children }: { children: ReactNode }) {
  const { connection, refreshAccessToken } = useSession();
  const [signal] = useState(createAppStateForegroundSignal);
  const [controller, setController] = useState<Controller | null>(null);

  useEffect(() => {
    let prev: GateInput = { connected: false, foreground: false };
    let current: Controller | null = null;
    const reconcile = (foreground: boolean) => {
      const next: GateInput = { connected: connection !== null, foreground };
      const action = controllerGateAction(prev, next);
      prev = next;
      if (action === "build") {
        current = buildController({ connection, refreshAccessToken });
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
  }, [connection, refreshAccessToken, signal]);

  if (!controller) {
    return (
      <ControllerContext.Provider value={null}>
        {children}
      </ControllerContext.Provider>
    );
  }
  return <LiveController controller={controller}>{children}</LiveController>;
}

function LiveController({
  controller,
  children,
}: {
  controller: Controller;
  children: ReactNode;
}) {
  const syncState = useSyncState(controller);
  return (
    <ControllerContext.Provider value={controller}>
      {syncState === "incompatible" ? <IncompatibleScreen /> : children}
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
