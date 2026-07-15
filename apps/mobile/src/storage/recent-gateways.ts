import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { z } from "zod";
import type { ConnectionConfig } from "@/api/types";
import { connectionSchema } from "@/storage/connection";
import {
  recentGatewayId,
  removeRecentGateway as removeFromIndex,
  upsertRecentGateway,
  type RecentGateway,
} from "./recent-gateway-model";

const RECENT_GATEWAY_INDEX_KEY = "vesta.recent-gateways.v1";
const RECENT_GATEWAY_SECRET_PREFIX = "vesta.recent-gateway.v1.";

const recentGatewaySchema = z.object({
  id: z.string().regex(/^[a-zA-Z0-9._-]+$/),
  url: z.string().url(),
  hosted: z.boolean(),
  lastConnectedAt: z.number().nonnegative(),
});
const recentGatewayIndexSchema = z.array(recentGatewaySchema);
const recentGatewayCredentialSchema = z.object({
  connection: connectionSchema,
  connectKey: z.string().min(1).optional(),
});

export interface RecentGatewayCredential {
  connection: ConnectionConfig;
  connectKey?: string;
}

function secretKey(id: string): string {
  return `${RECENT_GATEWAY_SECRET_PREFIX}${id}`;
}

export async function readRecentGateways(): Promise<RecentGateway[]> {
  const stored = await AsyncStorage.getItem(RECENT_GATEWAY_INDEX_KEY);
  if (!stored) return [];
  try {
    return recentGatewayIndexSchema.parse(JSON.parse(stored));
  } catch {
    await AsyncStorage.removeItem(RECENT_GATEWAY_INDEX_KEY);
    return [];
  }
}

export async function saveRecentGateway(
  connection: ConnectionConfig,
  options: {
    connectKey?: string;
    touch?: boolean;
    now?: number;
  } = {},
): Promise<RecentGateway[]> {
  const id = recentGatewayId(connection.url);
  const existing = await readRecentGatewayCredential(id);
  const credential: RecentGatewayCredential = {
    connection,
    connectKey: options.connectKey ?? existing?.connectKey,
  };
  await SecureStore.setItemAsync(secretKey(id), JSON.stringify(credential), {
    keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK,
  });

  const current = await readRecentGateways();
  const next = upsertRecentGateway(current, connection, {
    touch: options.touch ?? true,
    now: options.now ?? Date.now(),
  });
  await AsyncStorage.setItem(RECENT_GATEWAY_INDEX_KEY, JSON.stringify(next));
  return next;
}

export async function readRecentGatewayCredential(
  id: string,
): Promise<RecentGatewayCredential | null> {
  const stored = await SecureStore.getItemAsync(secretKey(id));
  if (!stored) return null;
  try {
    const credential = recentGatewayCredentialSchema.parse(JSON.parse(stored));
    if (recentGatewayId(credential.connection.url) !== id) return null;
    return credential;
  } catch {
    await SecureStore.deleteItemAsync(secretKey(id));
    return null;
  }
}

export async function forgetRecentGateway(
  id: string,
): Promise<RecentGateway[]> {
  const current = await readRecentGateways();
  const next = removeFromIndex(current, id);
  await AsyncStorage.setItem(RECENT_GATEWAY_INDEX_KEY, JSON.stringify(next));
  await SecureStore.deleteItemAsync(secretKey(id));
  return next;
}

export async function clearRecentGateways(): Promise<void> {
  const current = await readRecentGateways();
  await AsyncStorage.removeItem(RECENT_GATEWAY_INDEX_KEY);
  await Promise.all(
    current.map((gateway) =>
      SecureStore.deleteItemAsync(secretKey(gateway.id)),
    ),
  );
}
