import { createContext, useContext } from "react";
import type { Controller } from "@vesta/core";

// Context + hook live here, separate from the ControllerProvider component, so the
// ControllerContext identity is stable across Fast Refresh (matches GatewayProvider /
// AgentSocketProvider). A single controller serves the whole connection.
export const ControllerContext = createContext<Controller | null>(null);

export function useController(): Controller {
  const controller = useContext(ControllerContext);
  if (!controller) {
    throw new Error("useController must be used within ControllerProvider");
  }
  return controller;
}
