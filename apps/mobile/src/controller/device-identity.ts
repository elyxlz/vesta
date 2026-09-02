import { Platform } from "react-native";
import { pushInstallationId } from "@/notifications/PushCoordinator";

// This device's stable id (reused from push registration) and a self-composed label, reported up
// /sync so vestad tracks it in the device registry. Async because the id lives in AsyncStorage.
export async function deviceIdentity(): Promise<{
  id: string;
  descriptor: string;
}> {
  const id = await pushInstallationId();
  const os =
    Platform.OS === "ios"
      ? "iOS"
      : Platform.OS === "android"
        ? "Android"
        : "an unknown OS";
  return { id, descriptor: `Vesta Mobile on ${os}` };
}
