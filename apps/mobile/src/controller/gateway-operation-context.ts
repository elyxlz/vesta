import { createContext, use } from "react";
import type { GatewayOperation } from "@vesta/core";

// What the gateway is doing to itself, and what it just finished doing. Selected once from the
// replica by ControllerProvider: home renders both and the route effect blocks agent pages on the
// operation alone, so a resolution the user is still reading never holds the app on home.
export interface GatewayOperationState {
  operation: GatewayOperation | null;
  updatedTo: string | null;
}

export const GatewayOperationContext = createContext<GatewayOperationState>({
  operation: null,
  updatedTo: null,
});

export function useGatewayOperation(): GatewayOperationState {
  return use(GatewayOperationContext);
}
