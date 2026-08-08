import { createContext, use } from "react";
import type { GatewayOperation } from "@vesta/core";

// The gateway's running operation, selected once from the replica by ControllerProvider. Home
// renders it and the route effect blocks agent pages on it, so both read the same value.
export const GatewayOperationContext =
  createContext<GatewayOperation | null>(null);

export function useGatewayOperation(): GatewayOperation | null {
  return use(GatewayOperationContext);
}
