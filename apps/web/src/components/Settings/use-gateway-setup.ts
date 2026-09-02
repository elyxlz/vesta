import {
  fetchGatewayInfo,
  fetchGatewaySettings,
  type GatewayEndpointInfo,
  type GatewaySettings,
} from "@vesta/core";
import { useResource } from "@vesta/core/react";
import { httpClient } from "@/api/client";

export interface GatewaySetup {
  info: GatewayEndpointInfo;
  settings: GatewaySettings;
}

const loadSetup = async (): Promise<GatewaySetup> => {
  const [info, settings] = await Promise.all([
    fetchGatewayInfo(httpClient),
    fetchGatewaySettings(httpClient),
  ]);
  return { info, settings };
};

// One-shot read of the daemon's setup for the read-only Gateway "Setup" section: `undefined` until
// both fetches resolve, and stays hidden when they fail.
export function useGatewaySetup(): GatewaySetup | undefined {
  return useResource("setup", loadSetup).data ?? undefined;
}
