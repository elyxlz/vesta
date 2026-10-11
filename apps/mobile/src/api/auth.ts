import {
  GATEWAY_CONNECT_TIMEOUT_MS,
  mintConnection,
  refreshConnection,
  type ConnectionConfig,
} from "@vesta/core";

// Exchange a connect key for a session (core owns the wire flow and its reachability budget,
// GATEWAY_CONNECT_TIMEOUT_MS).
export function connectWithKey(
  url: string,
  apiKey: string,
): Promise<ConnectionConfig> {
  return mintConnection((input, init) => fetch(input, init), url, apiKey);
}

export { GATEWAY_CONNECT_TIMEOUT_MS };

// Revive a saved gateway session before reconnecting to it; an expired or refresh-less one asks
// for a fresh connect instead.
export async function resumeGatewaySession(
  connection: ConnectionConfig,
): Promise<ConnectionConfig> {
  const expired = new Error(
    "This saved gateway session has expired. Connect to it again.",
  );
  if (!connection.refreshToken) throw expired;
  const outcome = await refreshConnection(
    (input, init) => fetch(input, init),
    connection,
  );
  if (outcome.kind === "expired") throw expired;
  if (outcome.kind === "transient") {
    throw new Error("Could not restore this saved gateway session.");
  }
  return outcome.connection;
}
