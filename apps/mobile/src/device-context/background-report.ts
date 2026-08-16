import AsyncStorage from "@react-native-async-storage/async-storage";
import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";
import { isTokenExpiringSoon } from "@/api/client";
import { deviceIdentity } from "@/controller/device-identity";
import { PREFERENCES_KEY, readStoredPreferences } from "@/preferences/model";
import { readConnection } from "@/storage/connection";
import { readDeviceContext } from "./device-context";

// The OS-scheduled poll that reports the phone's zone and position while the app is closed, over
// `PUT /devices/{id}/context` (the socket needs a running app). iOS and Android decide when it runs;
// `minimumInterval` is a floor, not a schedule. It never touches the session: the app holds the
// live refresh token in memory, and a rotation from here would strand it, so an expiring access
// token skips the report and the next foreground open reports instead.
export const DEVICE_CONTEXT_TASK = "vesta-device-context";
export const BACKGROUND_REPORT_MIN_INTERVAL_MINUTES = 60;

export async function reportDeviceContextInBackground(): Promise<void> {
  const connection = await readConnection();
  if (!connection || isTokenExpiringSoon(connection)) return;
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
  const response = await fetch(
    `${connection.url}/devices/${encodeURIComponent(id)}/context`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${connection.accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(context),
    },
  );
  if (!response.ok) {
    throw new Error(`Device context report failed (${response.status}).`);
  }
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
