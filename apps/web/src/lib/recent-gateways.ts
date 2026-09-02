import type { ConnectionConfig } from "./connection";
import { field, numberField, stringField } from "@/lib/json-shape";
import { native } from "./native";
import { parseConnectionConfig } from "./native/parse-connection-config";

// Recently connected gateways, so the app can switch between them without
// re-pasting a connect link. A client convenience list (like the theme and
// mode prefs) held separately from the single active connection. The native
// bridge protects credentials with the OS credential store on desktop and
// uses the browser's same-origin storage for the web app.

export interface RecentGateway {
  id: string;
  url: string;
  hosted: boolean;
  lastConnectedAt: number;
  connection: ConnectionConfig;
}

// FNV-1a with two seeds: a stable id per gateway, so reconnecting the same
// origin updates one record instead of piling up. Two hashes widen the space
// enough that distinct origins never collide in practice.
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
  return `g${hashString(origin, 2_166_136_261)}${hashString(origin, 2_654_435_761)}`;
}

export function upsertRecentGateway(
  gateways: readonly RecentGateway[],
  entry: { connection: ConnectionConfig },
  options: { touch: boolean; now: number },
): RecentGateway[] {
  const id = recentGatewayId(entry.connection.url);
  const existing = gateways.find(
    (gateway) => gateway.id === id || gateway.url === entry.connection.url,
  );
  const next: RecentGateway = {
    id,
    url: entry.connection.url,
    hosted: entry.connection.hosted === true,
    lastConnectedAt:
      options.touch || !existing ? options.now : existing.lastConnectedAt,
    connection: entry.connection,
  };
  const remaining = gateways.filter(
    (gateway) => gateway.id !== id && gateway.url !== entry.connection.url,
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

function parseRecentGateway(value: unknown): RecentGateway | null {
  const connection = parseConnectionConfig(field(value, "connection"));
  if (connection === null) return null;
  const lastConnectedAt = numberField(value, "lastConnectedAt");
  if (lastConnectedAt === null) return null;
  return {
    id: stringField(value, "id") ?? recentGatewayId(connection.url),
    url: connection.url,
    hosted: connection.hosted === true,
    lastConnectedAt,
    connection,
  };
}

export async function readRecentGateways(): Promise<RecentGateway[]> {
  const parsed = await native.recentGatewayStore.read();
  if (!Array.isArray(parsed)) {
    if (parsed !== null) await native.recentGatewayStore.clear();
    return [];
  }
  return parsed
    .map(parseRecentGateway)
    .filter((gateway): gateway is RecentGateway => gateway !== null);
}

function writeRecentGateways(gateways: RecentGateway[]): Promise<void> {
  return native.recentGatewayStore.write(gateways);
}

export async function rememberGateway(
  connection: ConnectionConfig,
  options: { touch?: boolean } = {},
): Promise<RecentGateway[]> {
  const next = upsertRecentGateway(
    await readRecentGateways(),
    { connection },
    { touch: options.touch ?? true, now: Date.now() },
  );
  await writeRecentGateways(next);
  return next;
}

export async function rememberGatewayAfterConnect(
  connection: ConnectionConfig,
): Promise<void> {
  try {
    await rememberGateway(connection);
  } catch (cause) {
    console.warn("could not save the recent gateway", cause);
  }
}

export async function forgetRecentGateway(
  id: string,
): Promise<RecentGateway[]> {
  const next = removeRecentGateway(await readRecentGateways(), id);
  await writeRecentGateways(next);
  return next;
}
