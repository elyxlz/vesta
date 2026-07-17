import type { ConnectionConfig } from "@/api/types";

export interface RecentGateway {
  id: string;
  url: string;
  hosted: boolean;
  lastConnectedAt: number;
}

function hashString(value: string, seed: number): string {
  let hash = seed >>> 0;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16_777_619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

export function recentGatewayId(url: string): string {
  const origin = new URL(url).origin;
  const reversed = [...origin].reverse().join("");
  return `g${hashString(origin, 2_166_136_261)}${hashString(reversed, 2_654_435_761)}`;
}

export function upsertRecentGateway(
  gateways: readonly RecentGateway[],
  connection: ConnectionConfig,
  options: { touch: boolean; now: number },
): RecentGateway[] {
  const id = recentGatewayId(connection.url);
  const existing = gateways.find(
    (gateway) => gateway.id === id || gateway.url === connection.url,
  );
  const next: RecentGateway = {
    id,
    url: connection.url,
    hosted: connection.hosted,
    lastConnectedAt:
      options.touch || !existing ? options.now : existing.lastConnectedAt,
  };
  const remaining = gateways.filter(
    (gateway) => gateway.id !== id && gateway.url !== connection.url,
  );

  if (options.touch || !existing) return [next, ...remaining];
  return gateways.map((gateway) =>
    gateway.id === existing.id ? next : gateway,
  );
}

export function removeRecentGateway(
  gateways: readonly RecentGateway[],
  id: string,
): RecentGateway[] {
  return gateways.filter((gateway) => gateway.id !== id);
}
