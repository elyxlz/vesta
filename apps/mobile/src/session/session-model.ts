import type { ConnectionConfig } from "@vesta/core";

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

// The stored connection to adopt on foreground when another writer rotated the tokens while the app
// was suspended (the background device-context poll refreshes and writes SecureStore): the same
// gateway with newer tokens. Never adopts across a sign-out (no current) or a gateway switch.
export function rotatedStoredConnection(
  current: ConnectionConfig | null,
  stored: ConnectionConfig | null,
): ConnectionConfig | null {
  if (!current || !stored || changesGateway(current, stored)) return null;
  return stored.refreshToken !== current.refreshToken ? stored : null;
}
