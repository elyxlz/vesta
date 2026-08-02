import type { ApiClient } from "../../src/api/client";
import type { GatewayInfo, GatewaySettings } from "../../src/api/types";

const info: GatewayInfo = {
  lan: { exposed: true, url: "http://vesta.local:8080" },
  tunnel_url: "https://home.vesta.run",
  port: 8080,
};
const settings: GatewaySettings = {
  auto_update: true,
  channel: "stable",
  auto_backup: {
    enabled: true,
    hour: 3,
    retention: { daily: 7, weekly: 4, monthly: 6 },
  },
};

export async function fetchGatewayInfo(_api: ApiClient): Promise<GatewayInfo> {
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
