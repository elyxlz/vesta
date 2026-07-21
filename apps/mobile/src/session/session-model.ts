import type { ConnectionConfig } from "@/api/types";

export function changesGateway(
  current: ConnectionConfig | null,
  next: ConnectionConfig,
): boolean {
  return !current || current.url !== next.url || current.hosted !== next.hosted;
}

// The gateway identity that warrants a fresh controller (and socket): url + hosted, not
// the rotating tokens. A token refresh preserves this key, so the controller is reused and
// reauths in-band; only a gateway switch changes it and rebuilds.
export function connectionKeyOf(
  connection: ConnectionConfig | null,
): string | null {
  return connection ? `${connection.url}|${String(connection.hosted)}` : null;
}
