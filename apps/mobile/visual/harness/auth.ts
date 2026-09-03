import type { ConnectionConfig } from "@vesta/core";
import { visualDelay } from "./launch-query";

// The catalog documents the development build, where Vesta Cloud sign-in is offered.
export const cloudSignInEnabled = true;

export async function signInWithVestaAccount(): Promise<ConnectionConfig | null> {
  await new Promise((resolve) => setTimeout(resolve, 4_000));
  await visualDelay();
  throw new Error("Sign-in failed");
}

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
