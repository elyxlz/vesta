import type { ConnectionConfig } from "./connection";
import { parseConnectionConfig } from "./native/parse-connection-config";

// Recently connected gateways, so the app can switch between them without
// re-pasting a connect link. A client convenience list (like the theme and
// mode prefs) held in localStorage, separate from the single active connection
// the native bridge owns. Web has no keychain, so the credential rides in the
// same record; that matches the plaintext tier the active connection already
// lives in.
const STORAGE_KEY = "vesta-recent-gateways";

export interface RecentGateway {
  id: string;
  url: string;
  hosted: boolean;
  lastConnectedAt: number;
  connection: ConnectionConfig;
  // The self-host connect key, kept so a switch can mint a fresh session even
  // after the stored tokens die. Absent for hosted (vesta.run) gateways.
  connectKey?: string;
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
  entry: { connection: ConnectionConfig; connectKey?: string },
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
    connectKey: entry.connectKey ?? existing?.connectKey,
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
  if (value === null || typeof value !== "object") return null;
  const record = value as {
    id?: unknown;
    lastConnectedAt?: unknown;
    connection?: unknown;
    connectKey?: unknown;
  };
  const connection = parseConnectionConfig(record.connection);
  if (connection === null) return null;
  if (typeof record.lastConnectedAt !== "number") return null;
  return {
    id:
      typeof record.id === "string"
        ? record.id
        : recentGatewayId(connection.url),
    url: connection.url,
    hosted: connection.hosted === true,
    lastConnectedAt: record.lastConnectedAt,
    connection,
    connectKey:
      typeof record.connectKey === "string" ? record.connectKey : undefined,
  };
}

export function readRecentGateways(): RecentGateway[] {
  if (typeof localStorage === "undefined") return [];
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return [];
  }
  if (!Array.isArray(parsed)) {
    localStorage.removeItem(STORAGE_KEY);
    return [];
  }
  return parsed
    .map(parseRecentGateway)
    .filter((gateway): gateway is RecentGateway => gateway !== null);
}

function writeRecentGateways(gateways: RecentGateway[]): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(gateways));
}

export function rememberGateway(
  connection: ConnectionConfig,
  options: { connectKey?: string; touch?: boolean } = {},
): RecentGateway[] {
  const next = upsertRecentGateway(
    readRecentGateways(),
    { connection, connectKey: options.connectKey },
    { touch: options.touch ?? true, now: Date.now() },
  );
  writeRecentGateways(next);
  return next;
}

export function forgetRecentGateway(id: string): RecentGateway[] {
  const next = removeRecentGateway(readRecentGateways(), id);
  writeRecentGateways(next);
  return next;
}
