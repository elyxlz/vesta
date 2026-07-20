import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { usePathname, useRouter } from "expo-router";
import { registerMobileDevice, unregisterMobileDevice } from "@/api/endpoints";
import { createApiClient, type ApiClient } from "@/api/client";
import type { ConnectionConfig } from "@/api/types";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";
import {
  clearPushRegistration,
  readPushRegistration,
  writePushRegistration,
  type PushRegistrationSnapshot,
} from "@/storage/push-registration";
import { designTokens } from "@/theme/generated";
import { shouldPresentForegroundNotification } from "./foreground-policy";
import {
  notificationNavigationDecision,
  pendingNotificationFromData,
  readPendingNotification,
  type PendingNotification,
} from "./notification-routing";
import {
  gatewayHandoffDecision,
  isSameRegistration,
  pushRegistrationDecision,
  resolveHydratedSnapshot,
  type RegistrationTarget,
} from "./registration-policy";

const PUSH_TOKEN_KEY = "vesta.expo-push-token.v1";
const PUSH_INSTALLATION_ID_KEY = "vesta.push-installation-id.v1";
const PENDING_NOTIFICATION_KEY = "vesta.pending-notification.v1";
const PUSH_NOTIFICATIONS_ENABLED =
  Constants.expoConfig?.extra?.pushNotificationsEnabled !== false;

Notifications.setNotificationHandler({
  handleNotification: async (notification) => {
    const present = shouldPresentForegroundNotification(
      notification.request.content.data,
    );
    return {
      // Foreground presentation has one owner: while /sync is connected the user_notification delta
      // shows the notification, so the push is suppressed here (foreground-policy). When sync is down
      // the push is the fallback, suppressed only for the visible agent's healthy socket.
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

function registrationTarget(
  snapshot: PushRegistrationSnapshot | null,
): RegistrationTarget | null {
  return snapshot
    ? { gatewayUrl: snapshot.connection.url, token: snapshot.token }
    : null;
}

function EnabledPushCoordinator() {
  const router = useRouter();
  const pathname = usePathname();
  const session = useSession();
  const { reachable, agentsReady, agents } = useRoster();
  const preferences = usePreferences();
  const [pending, setPending] = useState<PendingNotification | null>(null);
  const processingNotification = useRef<string | null>(null);
  const registrationChain = useRef<Promise<void>>(Promise.resolve());
  // The gateway (with the credentials to reach it later) this device last registered a push token
  // with. Persisted so a switch or disconnect that spans an app restart can still unregister at the
  // old gateway; the ref alone would die with the process and strand it pushing. Set on every
  // successful registration, cleared once the old gateway's registration is torn down.
  const registrationSnapshot = useRef<PushRegistrationSnapshot | null>(null);
  const [snapshotHydrated, setSnapshotHydrated] = useState(false);
  // Latest full connection (creds and all) tracked out of band so the registration effect can
  // snapshot it without depending on the connection object identity, which churns on every token
  // refresh; the effect keys on the stable gateway url instead.
  const connectionRef = useRef<ConnectionConfig | null>(session.connection);

  const enqueue = useCallback((operation: () => Promise<void>): void => {
    const next = registrationChain.current.then(operation);
    registrationChain.current = next.catch(() => undefined);
    void next.catch((cause: unknown) => {
      console.warn(
        "Could not update remote notifications:",
        cause instanceof Error ? cause.message : cause,
      );
    });
  }, []);

  useEffect(() => {
    connectionRef.current = session.connection;
  }, [session.connection]);

  useEffect(() => {
    let active = true;
    void readPushRegistration()
      .then((stored) => {
        if (active) {
          registrationSnapshot.current = resolveHydratedSnapshot(
            registrationSnapshot.current,
            stored,
          );
        }
      })
      .catch((cause: unknown) => {
        console.warn("Could not restore push registration:", cause);
      })
      .finally(() => {
        if (active) setSnapshotHydrated(true);
      });
    return () => {
      active = false;
    };
  }, []);

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
      reachable,
      agentsReady,
      agentNames: agents.map((agent) => agent.name),
      routeReady,
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
  }, [
    pathname,
    pending,
    router,
    session,
    reachable,
    agentsReady,
    agents,
  ]);

  useEffect(() => {
    if (!snapshotHydrated) return;
    const snapshot = registrationSnapshot.current;
    const decision = gatewayHandoffDecision({
      previousGatewayUrl: snapshot?.connection.url ?? null,
      currentGatewayUrl: session.connection?.url ?? null,
      sessionStatus: session.status,
    });
    if (decision === "keep" || !snapshot) return;
    registrationSnapshot.current = null;
    enqueue(async () => {
      const oldApi = createApiClient({
        getConnection: () => snapshot.connection,
        onConnectionChange: async () => undefined,
        onSessionExpired: async () => undefined,
      });
      await unregisterMobileDevice(oldApi, snapshot.token);
      // Clear the persisted snapshot only if it still names the gateway we just tore down: the
      // registration effect may have written a newer one for the current gateway (both are
      // device-global singletons), and PUSH_TOKEN_KEY belongs to that current registration, so this
      // path never touches it. A thrown DELETE skips this tail, leaving the snapshot to retry next
      // launch.
      const stored = registrationTarget(await readPushRegistration());
      if (isSameRegistration(stored, registrationTarget(snapshot))) {
        await clearPushRegistration();
      }
    });
  }, [enqueue, snapshotHydrated, session.status, session.connection?.url]);

  useEffect(() => {
    // Gate on the snapshot restore so the handoff's DELETE(old) is always enqueued before this
    // effect's PUT(new): both share the serial registrationChain, and restoring first makes the
    // ordering deterministic across a relaunch instead of a race between two async reads.
    if (!snapshotHydrated) return;
    const registrationDecision = pushRegistrationDecision({
      preferencesHydrated: preferences.hydrated,
      sessionStatus: session.status,
      notificationsEnabled: preferences.remoteNotifications,
    });
    if (registrationDecision === "wait") return;
    let active = true;
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
      // Snapshot the exact connection we are about to register with, captured before the network
      // call, so an in-flight gateway switch can never leave the server row untracked: whatever we
      // PUT here is exactly what a later handoff will DELETE.
      const connection = connectionRef.current;
      if (!connection) return;
      await registerMobileDevice(session.api, {
        installationId,
        token: result.data,
        platform,
        gateway: connection.url,
        eventTypes,
        previews: preferences.notificationPreviews,
      });
      await AsyncStorage.setItem(PUSH_TOKEN_KEY, result.data);
      const snapshot: PushRegistrationSnapshot = {
        connection,
        token: result.data,
      };
      registrationSnapshot.current = snapshot;
      await writePushRegistration(snapshot);
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
    enqueue,
    preferences.hydrated,
    preferences.notificationPreviews,
    preferences.pushChatReplies,
    preferences.pushStatusChanges,
    preferences.remoteNotifications,
    session.api,
    session.connection?.url,
    session.status,
    snapshotHydrated,
  ]);

  return null;
}

export function PushCoordinator() {
  if (!PUSH_NOTIFICATIONS_ENABLED) return null;
  return <EnabledPushCoordinator />;
}

export async function unregisterCurrentMobileDevice(
  api: ApiClient,
): Promise<void> {
  await removeStoredRegistration(api);
}
