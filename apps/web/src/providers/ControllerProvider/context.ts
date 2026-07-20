import { createContext, useContext } from "react";
import type { Controller } from "@vesta/core";

// Context + hook live here, separate from the ControllerProvider component, so the
// ControllerContext identity is stable across Fast Refresh (matches GatewayProvider /
// AgentSocketProvider). A single controller serves the whole connection.
export const ControllerContext = createContext<Controller | null>(null);

// A no-op default so a consumer outside an ActiveController (before a controller exists)
// can call it harmlessly; the update path only fires once a controller exists.
export const ControllerReconnectContext = createContext<() => void>(
  () => undefined,
);

// Invariant: a consumer that can mount before a controller exists (e.g. GatewayProvider)
// must read the nullable ControllerContext directly, not useController().
export function useController(): Controller {
  const controller = useContext(ControllerContext);
  if (!controller) {
    throw new Error("useController must be used within ControllerProvider");
  }
  return controller;
}

export function useControllerReconnect(): () => void {
  return useContext(ControllerReconnectContext);
}
