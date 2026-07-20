import * as SecureStore from "expo-secure-store";
import { z } from "zod";
import type { ConnectionConfig } from "@/api/types";
import { connectionSchema } from "@/storage/connection";

const PUSH_REGISTRATION_KEY = "vesta.push-registration.v1";

export interface PushRegistrationSnapshot {
  connection: ConnectionConfig;
  token: string;
}

const snapshotSchema = z.object({
  connection: connectionSchema,
  token: z.string().min(1),
});

export async function readPushRegistration(): Promise<PushRegistrationSnapshot | null> {
  const stored = await SecureStore.getItemAsync(PUSH_REGISTRATION_KEY);
  if (!stored) return null;
  try {
    return snapshotSchema.parse(JSON.parse(stored));
  } catch {
    await SecureStore.deleteItemAsync(PUSH_REGISTRATION_KEY);
    return null;
  }
}

export async function writePushRegistration(
  snapshot: PushRegistrationSnapshot,
): Promise<void> {
  await SecureStore.setItemAsync(
    PUSH_REGISTRATION_KEY,
    JSON.stringify(snapshot),
    { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK },
  );
}

export async function clearPushRegistration(): Promise<void> {
  await SecureStore.deleteItemAsync(PUSH_REGISTRATION_KEY);
}
