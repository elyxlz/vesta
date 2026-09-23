import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { reportDeviceContext, type ConnectionConfig } from "@vesta/core";
import { createApiClient } from "@/api/client";
import { deviceIdentity } from "@/controller/device-identity";
import { PREFERENCES_KEY, readStoredPreferences } from "@/preferences/model";
import { readConnection, writeConnection } from "@/storage/connection";
import { readDeviceContext } from "./device-context";

// The background location task that reports the phone's zone and position while the app is closed,
// over `PUT /devices/{id}/context` (the socket needs a running app). The OS wakes it when the phone
// moves: on iOS the significant-change monitor alone (cell and Wi-Fi, about 500 m, relaunching a
// killed app), so the GPS and the status-bar arrow stay off between wake-ups; on Android the fused
// provider, which Android limits to a few background updates an hour with no foreground service.
// It refreshes an expiring session like the app does and writes the rotated tokens to SecureStore,
// which the suspended app adopts on foreground (`SessionProvider`), so a rotation from here never
// strands it. It never signs the user out.
export const DEVICE_CONTEXT_TASK = "vesta-device-context";
export const BACKGROUND_REPORT_MIN_DISTANCE_M = 500;

// `significantChangesOnly` is read by the iOS task consumer patch in `patches/expo-location+*.patch`.
const BACKGROUND_LOCATION_OPTIONS: Location.LocationTaskOptions & {
  significantChangesOnly: boolean;
} = {
  accuracy: Location.Accuracy.Balanced,
  distanceInterval: BACKGROUND_REPORT_MIN_DISTANCE_M,
  significantChangesOnly: true,
};

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

TaskManager.defineTask(DEVICE_CONTEXT_TASK, async ({ error }) => {
  if (error) {
    console.warn("Background location update failed:", error.message);
    return;
  }
  try {
    await reportDeviceContextInBackground();
  } catch (cause) {
    console.warn("Background device context report failed:", cause);
  }
});

// Runs on each foreground edge, so a grant changed in the OS Settings lands on the next open.
// Starting an already started task only reapplies its options.
export async function syncBackgroundReport(
  shareLocation: boolean,
): Promise<void> {
  const background = await Location.getBackgroundPermissionsAsync();
  if (shareLocation && background.granted) {
    await Location.startLocationUpdatesAsync(
      DEVICE_CONTEXT_TASK,
      BACKGROUND_LOCATION_OPTIONS,
    );
    return;
  }
  if (await Location.hasStartedLocationUpdatesAsync(DEVICE_CONTEXT_TASK)) {
    await Location.stopLocationUpdatesAsync(DEVICE_CONTEXT_TASK);
  }
}
