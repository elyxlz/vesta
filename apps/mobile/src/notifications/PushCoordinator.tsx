import AsyncStorage from "@react-native-async-storage/async-storage";
import { useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { usePathname, useRouter } from "expo-router";
import { registerMobileDevice, unregisterMobileDevice } from "@/api/endpoints";
import type { ApiClient } from "@/api/client";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { designTokens } from "@/theme/generated";
import { shouldPresentForegroundNotification } from "./foreground-policy";
import {
  notificationNavigationDecision,
  pendingNotificationFromData,
  readPendingNotification,
  type PendingNotification,
} from "./notification-routing";
import { pushRegistrationDecision } from "./registration-policy";

const PUSH_TOKEN_KEY = "vesta.expo-push-token.v1";
const PUSH_INSTALLATION_ID_KEY = "vesta.push-installation-id.v1";
const PENDING_NOTIFICATION_KEY = "vesta.pending-notification.v1";

Notifications.setNotificationHandler({
  handleNotification: async (notification) => {
    const present = shouldPresentForegroundNotification(
      notification.request.content.data,
    );
    return {
      // Hide only when this exact agent is visible and its canonical socket is
      // healthy. Home, settings, another agent, and reconnecting states still
      // receive the notification normally.
      shouldShowBanner: present,
      shouldShowList: present,
      shouldPlaySound: present,
      shouldSetBadge: false,
    };
  },
});

function configuredProjectId(): string | null {
  if (Constants.easConfig?.projectId) return Constants.easConfig.projectId;
  const extra = Constants.expoConfig?.extra;
  if (!extra || typeof extra !== "object") return null;
  const eas = extra.eas;
  if (!eas || typeof eas !== "object" || !("projectId" in eas)) return null;
  return typeof eas.projectId === "string" ? eas.projectId : null;
}

async function pushInstallationId(): Promise<string> {
  const stored = await AsyncStorage.getItem(PUSH_INSTALLATION_ID_KEY);
  if (stored) return stored;
  const installationId = Crypto.randomUUID();
  await AsyncStorage.setItem(PUSH_INSTALLATION_ID_KEY, installationId);
  return installationId;
}

async function removeStoredRegistration(api: ApiClient): Promise<void> {
  const token = await AsyncStorage.getItem(PUSH_TOKEN_KEY);
  if (!token) return;
  await unregisterMobileDevice(api, token);
  await AsyncStorage.removeItem(PUSH_TOKEN_KEY);
}

export function PushCoordinator() {
  const router = useRouter();
  const pathname = usePathname();
  const session = useSession();
  const preferences = usePreferences();
  const [pending, setPending] = useState<PendingNotification | null>(null);
  const processingNotification = useRef<string | null>(null);
  const registrationChain = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    let active = true;
    const capture = async (
      response: Notifications.NotificationResponse | null,
    ): Promise<void> => {
      if (!response) return;
      const next = pendingNotificationFromData(
        response.notification.request.content.data,
        response.notification.request.identifier,
      );
      if (!next) {
        await Notifications.clearLastNotificationResponseAsync();
        return;
      }
      try {
        await AsyncStorage.setItem(
          PENDING_NOTIFICATION_KEY,
          JSON.stringify(next),
        );
        if (active) setPending(next);
        await Notifications.clearLastNotificationResponseAsync();
      } catch (cause: unknown) {
        console.warn("Could not preserve notification navigation:", cause);
        if (active) setPending(next);
      }
    };
    const subscription = Notifications.addNotificationResponseReceivedListener(
      (response) => {
        void capture(response);
      },
    );
    void AsyncStorage.getItem(PENDING_NOTIFICATION_KEY).then((stored) => {
      const restored = readPendingNotification(stored);
      if (active && restored) setPending((current) => current ?? restored);
    });
    void Notifications.getLastNotificationResponseAsync().then((response) =>
      capture(response),
    );
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (!pending) return;
    const routeReady = !["/connect", "/connect-link", "/scan"].includes(
      pathname,
    );
    const decision = notificationNavigationDecision({
      pending,
      sessionStatus: session.status,
      reachable: session.reachable,
      agentsReady: session.agentsReady,
      agentNames: session.agents.map((agent) => agent.name),
      routeReady,
      compatible: session.compatibility?.compatible ?? null,
      currentGateway: session.connection?.url ?? null,
    });
    if (decision === "wait") return;
    if (processingNotification.current === pending.identifier) return;
    processingNotification.current = pending.identifier;
    void AsyncStorage.removeItem(PENDING_NOTIFICATION_KEY)
      .catch((cause: unknown) => {
        console.warn("Could not clear notification navigation:", cause);
      })
      .finally(() => {
        if (decision === "open") {
          router.push({
            pathname: "/agent/[name]",
            params: { name: pending.agent },
          });
        }
        setPending((current) =>
          current?.identifier === pending.identifier ? null : current,
        );
        if (processingNotification.current === pending.identifier) {
          processingNotification.current = null;
        }
      });
  }, [pathname, pending, router, session]);

  useEffect(() => {
    const registrationDecision = pushRegistrationDecision({
      preferencesHydrated: preferences.hydrated,
      sessionStatus: session.status,
      notificationsEnabled: preferences.remoteNotifications,
    });
    if (registrationDecision === "wait") return;
    let active = true;
    const enqueue = (operation: () => Promise<void>): void => {
      const next = registrationChain.current.then(operation);
      registrationChain.current = next.catch(() => undefined);
      void next.catch((cause: unknown) => {
        console.warn(
          "Could not update remote notifications:",
          cause instanceof Error ? cause.message : cause,
        );
      });
    };
    if (registrationDecision === "unregister") {
      enqueue(async () => {
        await removeStoredRegistration(session.api);
      });
      return;
    }
    const platform = Platform.OS;
    if (!Device.isDevice || (platform !== "ios" && platform !== "android"))
      return;
    const gateway = session.connection?.url;
    if (!gateway) return;
    const eventTypes = [
      ...(preferences.pushChatReplies ? ["chat"] : []),
      ...(preferences.pushStatusChanges ? ["status"] : []),
    ];
    let permissionGranted = false;
    const registerExpoToken = async (
      devicePushToken?: Notifications.DevicePushToken,
    ): Promise<void> => {
      const projectId = configuredProjectId();
      if (!projectId) {
        console.warn("Remote notifications require an EAS project ID.");
        return;
      }
      const result = await Notifications.getExpoPushTokenAsync({
        projectId,
        devicePushToken,
      });
      if (!active) return;
      const installationId = await pushInstallationId();
      if (!active) return;
      await registerMobileDevice(session.api, {
        installationId,
        token: result.data,
        platform,
        gateway,
        eventTypes,
        previews: preferences.notificationPreviews,
      });
      await AsyncStorage.setItem(PUSH_TOKEN_KEY, result.data);
    };
    enqueue(async () => {
      if (!active) return;
      if (platform === "android") {
        await Notifications.setNotificationChannelAsync("vesta", {
          name: "Vesta",
          importance: Notifications.AndroidImportance.HIGH,
          vibrationPattern: [0, 180, 120, 180],
          lightColor: designTokens.colors.dark.primary,
        });
      }
      const current = await Notifications.getPermissionsAsync();
      const permission = current.granted
        ? current
        : await Notifications.requestPermissionsAsync({
            ios: { allowAlert: true, allowBadge: true, allowSound: true },
          });
      permissionGranted = permission.granted;
      if (!permissionGranted || !active) return;
      await registerExpoToken();
    });
    const tokenSubscription = Notifications.addPushTokenListener(
      (devicePushToken) => {
        enqueue(async () => {
          if (!permissionGranted || !active) return;
          await registerExpoToken(devicePushToken);
        });
      },
    );
    return () => {
      active = false;
      tokenSubscription.remove();
    };
  }, [
    preferences.hydrated,
    preferences.notificationPreviews,
    preferences.pushChatReplies,
    preferences.pushStatusChanges,
    preferences.remoteNotifications,
    session.api,
    session.connection?.url,
    session.status,
  ]);

  return null;
}

export async function unregisterCurrentMobileDevice(
  api: ApiClient,
): Promise<void> {
  await removeStoredRegistration(api);
}
