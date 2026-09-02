import AsyncStorage from "@react-native-async-storage/async-storage";
import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";
import { reportDeviceContext, type ConnectionConfig } from "@vesta/core";
import { createApiClient } from "@/api/client";
import { deviceIdentity } from "@/controller/device-identity";
import { PREFERENCES_KEY, readStoredPreferences } from "@/preferences/model";
import { readConnection, writeConnection } from "@/storage/connection";
import { readDeviceContext } from "./device-context";

// The OS-scheduled poll that reports the phone's zone and position while the app is closed, over
// `PUT /devices/{id}/context` (the socket needs a running app). iOS and Android decide when it runs;
// `minimumInterval` is a floor, not a schedule. It refreshes an expiring session like the app does
// and writes the rotated tokens to SecureStore, which the suspended app adopts on foreground
// (`SessionProvider`), so a rotation from here never strands it. It never signs the user out.
export const DEVICE_CONTEXT_TASK = "vesta-device-context";
export const BACKGROUND_REPORT_MIN_INTERVAL_MINUTES = 60;

export async function reportDeviceContextInBackground(): Promise<void> {
  let connection: ConnectionConfig | null = await readConnection();
  if (!connection) return;
  const preferences = readStoredPreferences(
    await AsyncStorage.getItem(PREFERENCES_KEY),
  );
  const [{ id }, context] = await Promise.all([
    deviceIdentity(),
    readDeviceContext({
      shareLocation: preferences.shareLocation,
      mode: "background",
    }),
  ]);
  if (context.timezone === undefined && context.position === undefined) return;
  const api = createApiClient({
    getConnection: () => connection,
    onConnectionChange: async (next) => {
      connection = next;
      await writeConnection(next);
    },
    onSessionExpired: () => Promise.resolve(),
  });
  await reportDeviceContext(api, id, context);
}

TaskManager.defineTask(DEVICE_CONTEXT_TASK, async () => {
  try {
    await reportDeviceContextInBackground();
    return BackgroundTask.BackgroundTaskResult.Success;
  } catch (cause) {
    console.warn("Background device context report failed:", cause);
    return BackgroundTask.BackgroundTaskResult.Failed;
  }
});

// Idempotent: registering an already-registered task is a no-op on both platforms, and a device
// where background tasks are restricted (Low Power Mode, an unsupported OS) simply never runs it.
export async function registerBackgroundReport(): Promise<void> {
  const status = await BackgroundTask.getStatusAsync();
  if (status !== BackgroundTask.BackgroundTaskStatus.Available) return;
  await BackgroundTask.registerTaskAsync(DEVICE_CONTEXT_TASK, {
    minimumInterval: BACKGROUND_REPORT_MIN_INTERVAL_MINUTES,
  });
}
