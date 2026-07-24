import * as SecureStore from "expo-secure-store";
import { z } from "zod";
import type { ConnectionConfig } from "@/api/types";

const CONNECTION_KEY = "vesta.connection.v1";

export const connectionSchema = z.object({
  url: z.string().url(),
  accessToken: z.string().min(1),
  refreshToken: z.string(),
  expiresAt: z.number(),
  hosted: z.boolean(),
});

export async function readConnection(): Promise<ConnectionConfig | null> {
  const stored = await SecureStore.getItemAsync(CONNECTION_KEY);
  if (!stored) return null;
  try {
    return connectionSchema.parse(JSON.parse(stored));
  } catch {
    await SecureStore.deleteItemAsync(CONNECTION_KEY);
    return null;
  }
}

export async function writeConnection(
  connection: ConnectionConfig,
): Promise<void> {
  await SecureStore.setItemAsync(CONNECTION_KEY, JSON.stringify(connection), {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK,
  });
}

export async function clearConnection(): Promise<void> {
  await SecureStore.deleteItemAsync(CONNECTION_KEY);
}
