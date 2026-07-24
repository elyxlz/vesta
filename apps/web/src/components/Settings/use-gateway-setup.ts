import { useEffect, useState } from "react";
import {
  fetchGatewayInfo,
  fetchGatewaySettings,
  type GatewayInfo,
  type GatewaySettings,
} from "@/api/gateway";

export interface GatewaySetup {
  info: GatewayInfo;
  settings: GatewaySettings;
}

// One-shot read of the daemon's setup for the read-only Gateway "Setup" section.
// Mirrors useAgentDefaults: `undefined` until both fetches resolve; the section
// renders nothing until then rather than flashing partial state.
export function useGatewaySetup(): GatewaySetup | undefined {
  const [setup, setSetup] = useState<GatewaySetup | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchGatewayInfo(), fetchGatewaySettings()])
      .then(([info, settings]) => {
        if (!cancelled) setSetup({ info, settings });
      })
      .catch(() => {
        /* noop: the section stays hidden when the fetch fails */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return setup;
}
