import type { ConnectionConfig } from "@vesta/core";
import { visualDelay } from "./launch-query";

export async function connectWithKey(
  _url: string,
  _apiKey: string,
): Promise<ConnectionConfig> {
  await visualDelay();
  throw new Error("Could not reach this Vesta gateway.");
}

export async function resumeGatewaySession(
  _connection: ConnectionConfig,
): Promise<ConnectionConfig> {
  throw new Error("Could not restore this saved gateway session.");
}

export async function assertGatewayReachable(_url: string): Promise<void> {
  await visualDelay();
  throw new Error("Could not reach this Vesta gateway.");
}
