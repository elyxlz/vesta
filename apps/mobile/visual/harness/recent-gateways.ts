import type { ConnectionConfig } from "@/api/types";
import type { RecentGateway } from "@/storage/recent-gateway-model";

export interface RecentGatewayCredential {
  connection: ConnectionConfig;
  connectKey?: string;
}

const initialGateways: RecentGateway[] = [
  {
    id: "visual-home",
    url: "https://home.vesta.run",
    hosted: true,
    lastConnectedAt: Date.UTC(2026, 6, 30, 9, 41),
  },
  {
    id: "visual-studio",
    url: "https://studio.vesta.local",
    hosted: false,
    lastConnectedAt: Date.UTC(2026, 6, 28, 18, 24),
  },
  {
    id: "visual-travel",
    url: "https://travel.vesta.run",
    hosted: true,
    lastConnectedAt: Date.UTC(2026, 6, 21, 7, 12),
  },
];

let gateways = [...initialGateways];

export async function readRecentGateways(): Promise<RecentGateway[]> {
  return [...gateways];
}

export async function saveRecentGateway(): Promise<RecentGateway[]> {
  return [...gateways];
}

export async function readRecentGatewayCredential(
  _id: string,
): Promise<RecentGatewayCredential | null> {
  await new Promise((resolve) => setTimeout(resolve, 5_000));
  return null;
}

export async function forgetRecentGateway(
  id: string,
): Promise<RecentGateway[]> {
  gateways = gateways.filter((gateway) => gateway.id !== id);
  return [...gateways];
}

export async function clearRecentGateways(): Promise<void> {
  gateways = [];
}
