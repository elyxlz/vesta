import type { DeviceContext } from "../protocol/frames";
import { jsonInit, type HttpClient } from "../transport/http";

// The out-of-socket carrier of a device's reported context (PUT /devices/{id}/context): what the
// mobile background poll writes while the app is suspended and no /sync socket is open.
export async function reportDeviceContext(
  http: HttpClient,
  deviceId: string,
  context: DeviceContext,
): Promise<void> {
  await http.request(
    `/devices/${encodeURIComponent(deviceId)}/context`,
    jsonInit("PUT", context),
  );
}

export interface MobileDeviceRegistration {
  installationId: string;
  token: string;
  platform: "ios" | "android";
  gateway: string;
  eventTypes: string[];
  previews: boolean;
}

// Register this phone's Expo push token with the gateway (PUT /mobile/devices).
export async function registerMobileDevice(
  http: HttpClient,
  input: MobileDeviceRegistration,
): Promise<void> {
  await http.request(
    "/mobile/devices",
    jsonInit("PUT", {
      installation_id: input.installationId,
      token: input.token,
      platform: input.platform,
      gateway: input.gateway,
      event_types: input.eventTypes,
      previews: input.previews,
    }),
  );
}

export async function unregisterMobileDevice(
  http: HttpClient,
  token: string,
): Promise<void> {
  await http.request("/mobile/devices", jsonInit("DELETE", { token }));
}
