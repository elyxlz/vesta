import type { ApiClient } from "../../src/api/client";
import type { GatewayEndpointInfo, GatewaySettings } from "@vesta/core";
import { visualSwitch } from "./launch-query";

// visualTunnel=unavailable reports no public tunnel.
const info: GatewayEndpointInfo = {
  lan: { exposed: true, url: "http://vesta.local:8080" },
  tunnel_url:
    visualSwitch("visualTunnel") === "unavailable"
      ? null
      : "https://home.vesta.run",
  port: 8080,
};
const settings: GatewaySettings = {
  auto_update: true,
  channel: "stable",
  auto_backup: {
    enabled: true,
    every_n_days: 3,
    retention: { periodic: 2, pre_update_versions: 2 },
  },
};

export async function fetchGatewayInfo(
  _api: ApiClient,
): Promise<GatewayEndpointInfo> {
  return info;
}

export async function fetchGatewaySettings(
  _api: ApiClient,
): Promise<GatewaySettings> {
  return settings;
}

export async function updateGatewaySettings(
  _api: ApiClient,
  patch: Partial<Pick<GatewaySettings, "auto_update" | "channel">>,
): Promise<GatewaySettings> {
  return { ...settings, ...patch };
}
