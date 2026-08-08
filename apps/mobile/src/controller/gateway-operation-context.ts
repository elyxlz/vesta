import { createContext, use } from "react";
import type { GatewayUpdateOperation } from "@vesta/core";

// The gateway's running operation, selected once from the replica by ControllerProvider. Home
// renders it and the route effect blocks agent pages on it, so both read the same value.
export const GatewayOperationContext =
  createContext<GatewayUpdateOperation | null>(null);

export function useGatewayOperation(): GatewayUpdateOperation | null {
  return use(GatewayOperationContext);
}
