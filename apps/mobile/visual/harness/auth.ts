import type { ConnectionConfig } from "@/api/types";

export async function signInWithVestaAccount(): Promise<
  ConnectionConfig | null
> {
  await new Promise((resolve) => setTimeout(resolve, 4_000));
  throw new Error("Sign-in failed");
}

export async function connectWithKey(
  _url: string,
  _apiKey: string,
): Promise<ConnectionConfig> {
  throw new Error("Could not reach this Vesta gateway.");
}

export async function resumeGatewaySession(
  _connection: ConnectionConfig,
): Promise<ConnectionConfig> {
  throw new Error("Could not restore this saved gateway session.");
}

export async function assertGatewayReachable(_url: string): Promise<void> {
  throw new Error("Could not reach this Vesta gateway.");
}
