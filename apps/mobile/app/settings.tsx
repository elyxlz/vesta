import { useState } from "react";
import { ActivityIndicator, Alert, Linking, StyleSheet } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Location from "expo-location";
import { useRouter } from "expo-router";
import {
  checkForGatewayUpdate,
  triggerGatewayRestart,
  triggerGatewayUpdate,
  type DeviceInfo,
  type ReleaseChannel,
} from "@vesta/core";
import {
  fetchGatewayInfo,
  fetchGatewaySettings,
  updateGatewaySettings,
} from "@/api/endpoints";
import type { GatewayInfo, GatewaySettings } from "@/api/types";
import { Screen } from "@/components/layout/Screen";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { useToast } from "@/components/native-toast";
import { Button, ButtonGroup } from "@/components/ui/Button";
import { FormRow, FormSection, SwitchRow } from "@/components/ui/Form";
import { unregisterCurrentMobileDevice } from "@/notifications/PushCoordinator";
import {
  usePreferences,
  type ThemePreference,
} from "@/preferences/PreferencesProvider";
import { usePrivacy } from "@/privacy/privacy-provider";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";

const IS_IOS = process.env.EXPO_OS === "ios";
const appearanceValueIcons = {
  light: "sunny-outline",
  dark: "moon-outline",
} as const;
type GatewayQueryData = {
  info: GatewayInfo;
  settings: GatewaySettings;
};

function titleCaseChannel(channel: ReleaseChannel | undefined): string {
  if (!channel) return "unknown";
  return channel === "beta" ? "Beta" : "Stable";
}

function lastSeenLabel(lastSeen: string): string {
  const then = new Date(lastSeen).getTime();
  if (Number.isNaN(then)) return "last seen recently";
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${String(mins)}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${String(hours)}h ago`;
  return `${String(Math.floor(hours / 24))}d ago`;
}

// The device's reported place and zone, falling back to the gateway's IP-derived location.
function deviceContextLine(device: DeviceInfo): string | undefined {
  const place = device.position?.place;
  const placeLabel =
    place && (place.city ?? place.region)
      ? [place.city ?? place.region, place.country].filter(Boolean).join(", ")
      : device.location;
  const parts = [placeLabel, device.timezone].filter(
    (part): part is string => typeof part === "string" && part.length > 0,
  );
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

export default function SettingsScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useSession();
  const roster = useRoster();
  const preferences = usePreferences();
  const privacy = usePrivacy();
  const { showError } = useToast();
  const gatewayQueryKey = ["gateway", session.connection?.url] as const;
  const [privacySaving, setPrivacySaving] = useState(false);
  const gateway = useQuery({
    queryKey: gatewayQueryKey,
    queryFn: async () => {
      const [info, settings] = await Promise.all([
        fetchGatewayInfo(session.api),
        fetchGatewaySettings(session.api),
      ]);
      return { info, settings };
    },
    enabled: session.status === "connected",
  });
  // The check just asks vestad to refresh; the fresh updateAvailable/latestVersion land in the
  // replica (roster) as a /sync gateway delta, so the UI reads them from there, never the POST body.
  const updateCheck = useMutation({
    mutationFn: () => checkForGatewayUpdate(session.api),
    onError: (error) => showError(error, "Could not check for updates"),
  });
  const gatewayUpdate = useMutation({
    mutationFn: () => triggerGatewayUpdate(session.api),
    onError: (error) => showError(error, "Could not update the gateway"),
  });
  // A restart drops every agent connection briefly like an update; the live socket self-heals on
  // its own once the gateway comes back, so nothing forces a reconnect here.
  const gatewayRestart = useMutation({
    mutationFn: () => triggerGatewayRestart(session.api),
    onError: (error) => showError(error, "Could not restart the gateway"),
  });
  const gatewaySettings = useMutation({
    mutationFn: (
      patch: Partial<
        Pick<GatewaySettings, "auto_update" | "user_context" | "channel">
      >,
    ) => updateGatewaySettings(session.api, patch),
    onMutate: async (patch) => {
      await queryClient.cancelQueries({ queryKey: gatewayQueryKey });
      const previous =
        queryClient.getQueryData<GatewayQueryData>(gatewayQueryKey);
      queryClient.setQueryData<GatewayQueryData>(gatewayQueryKey, (current) =>
        current
          ? {
              ...current,
              settings: { ...current.settings, ...patch },
            }
          : current,
      );
      return { previous };
    },
    onError: (error, _patch, context) => {
      if (context?.previous) {
        queryClient.setQueryData(gatewayQueryKey, context.previous);
      }
      showError(error, "Could not update the gateway");
    },
    onSuccess: (settings, patch) => {
      queryClient.setQueryData<GatewayQueryData>(gatewayQueryKey, (current) =>
        current ? { ...current, settings } : current,
      );
      if (patch.channel) {
        void checkForGatewayUpdate(session.api).catch((error: unknown) =>
          console.warn("[settings] update check failed:", error),
        );
      }
    },
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: gatewayQueryKey }),
  });
  const updateAvailable = roster.updateAvailable;
  const resolvedAppearance =
    preferences.theme === "system"
      ? preferences.dark
        ? "dark"
        : "light"
      : preferences.theme;
  const appearanceValueIcon = appearanceValueIcons[resolvedAppearance];
  const gatewayControlsDisabled =
    !gateway.data || !roster.reachable || gatewaySettings.isPending;

  const confirmGatewayUpdate = () => {
    Alert.alert("Update gateway?", "Agents will briefly restart.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Update",
        onPress: () => gatewayUpdate.mutate(),
      },
    ]);
  };

  const confirmGatewayRestart = () => {
    Alert.alert(
      "Restart gateway?",
      "Agent connections drop briefly and reconnect on their own.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Restart",
          onPress: () => gatewayRestart.mutate(),
        },
      ],
    );
  };

  const chooseTheme = () => {
    const select = (theme: ThemePreference) => {
      void preferences.update({ theme });
    };
    Alert.alert("Appearance", undefined, [
      { text: "System", onPress: () => select("system") },
      { text: "Light", onPress: () => select("light") },
      { text: "Dark", onPress: () => select("dark") },
      { text: "Cancel", style: "cancel" },
    ]);
  };

  const changeAppLock = async (enabled: boolean) => {
    setPrivacySaving(true);
    try {
      await privacy.setAppLockEnabled(enabled);
    } catch (error) {
      showError(error, "App Lock is unavailable");
    } finally {
      setPrivacySaving(false);
    }
  };

  const changeShareLocation = async (enabled: boolean) => {
    try {
      if (enabled) {
        const foreground = await Location.requestForegroundPermissionsAsync();
        if (!foreground.granted) {
          showError(
            new Error("Allow location for Vesta in system settings to share it."),
            "Location is not allowed",
          );
          return;
        }
        // The always-on grant is what lets the closed-app poll read a fix; the OS asks in its own
        // way (iOS a second prompt, Android a settings screen). Declined, sharing still works while
        // the app is open, so the switch turns on either way.
        await Location.requestBackgroundPermissionsAsync();
      }
      await preferences.update({ shareLocation: enabled });
    } catch (error) {
      showError(error, "Location sharing is unavailable");
    }
  };

  const changeAppSwitcherPrivacy = async (enabled: boolean) => {
    setPrivacySaving(true);
    try {
      await privacy.setHideAppSwitcherPreview(enabled);
    } catch (error) {
      showError(error, "Could not update privacy");
    } finally {
      setPrivacySaving(false);
    }
  };

  const chooseReleaseChannel = () => {
    if (gatewayControlsDisabled) return;
    const select = (channel: ReleaseChannel) => {
      if (channel !== gateway.data?.settings.channel) {
        gatewaySettings.mutate({ channel });
      }
    };
    Alert.alert(
      "Release channel",
      "Beta receives prereleases first. Switching to Stable never downgrades the current gateway.",
      [
        { text: "Stable", onPress: () => select("stable") },
        { text: "Beta", onPress: () => select("beta") },
        { text: "Cancel", style: "cancel" },
      ],
    );
  };

  return (
    <Screen contentStyle={styles.content}>
      <NativeSheetCloseButton
        accessibilityLabel="Close settings"
        visibleFromDetentIndex={1}
      />
      <FormSection
        title="Experience"
        actions={
          <Button
            pill
            variant="card"
            trailingIcon={appearanceValueIcon}
            accessibilityLabel={`Appearance, ${resolvedAppearance}${
              preferences.theme === "system" ? " from system setting" : ""
            }`}
            onPress={chooseTheme}
          >
            Appearance
          </Button>
        }
      />

      <FormSection title="Privacy">
        <SwitchRow
          label="App Lock"
          detail={`Require ${privacy.authenticationName} when returning to Vesta.`}
          value={privacy.appLockEnabled}
          disabled={!privacy.hydrated || privacySaving}
          onValueChange={(value) => void changeAppLock(value)}
        />
        <SwitchRow
          label="Hide in app switcher"
          detail={
            privacy.appLockEnabled
              ? "Always enabled while App Lock is on."
              : IS_IOS
                ? "Blur Vesta in the app switcher and during interruptions."
                : "Hide Vesta in recent apps and block screen capture."
          }
          value={privacy.appLockEnabled || privacy.hideAppSwitcherPreview}
          disabled={
            !privacy.hydrated || privacySaving || privacy.appLockEnabled
          }
          onValueChange={(value) => void changeAppSwitcherPrivacy(value)}
        />
        <SwitchRow
          label="Share device location"
          detail="Tell your agents where this phone is, place and coordinates, so plans and reminders follow your travel. Allow location always to keep sharing while the app is closed. Your timezone is always shared."
          value={preferences.shareLocation}
          onValueChange={(value) => void changeShareLocation(value)}
        />
      </FormSection>

      <FormSection title="Notifications">
        <SwitchRow
          label="Allow notifications"
          detail="Receive selected agent updates when the app is closed."
          value={preferences.remoteNotifications}
          onValueChange={(value) =>
            void preferences.update({ remoteNotifications: value })
          }
        />
        <SwitchRow
          label="Chat replies"
          detail="Notify when an agent sends a completed chat reply."
          value={preferences.remoteNotifications && preferences.pushChatReplies}
          disabled={!preferences.remoteNotifications}
          onValueChange={(value) =>
            void preferences.update({ pushChatReplies: value })
          }
        />
        <SwitchRow
          label="Show message content"
          detail="Show chat text on the lock screen. Off keeps messages private."
          value={
            preferences.remoteNotifications &&
            preferences.pushChatReplies &&
            preferences.notificationPreviews
          }
          disabled={
            !preferences.remoteNotifications || !preferences.pushChatReplies
          }
          onValueChange={(value) =>
            void preferences.update({ notificationPreviews: value })
          }
        />
        <SwitchRow
          label="Status changes"
          detail="Notify when an agent starts, stops, or changes availability."
          value={
            preferences.remoteNotifications && preferences.pushStatusChanges
          }
          disabled={!preferences.remoteNotifications}
          onValueChange={(value) =>
            void preferences.update({ pushStatusChanges: value })
          }
        />
      </FormSection>

      <FormSection
        title="Gateway"
        actions={
          <ButtonGroup>
            <Button
              variant="cardGrouped"
              loading={gatewayUpdate.isPending || updateCheck.isPending}
              onPress={
                updateAvailable
                  ? confirmGatewayUpdate
                  : () => updateCheck.mutate()
              }
            >
              {updateCheck.isPending
                ? "Checking for updates"
                : updateAvailable
                  ? "Update gateway"
                  : updateCheck.isError
                    ? "Retry update check"
                    : updateCheck.isSuccess
                      ? "Check again for updates"
                      : "Check for updates"}
            </Button>
            <Button
              variant="cardGrouped"
              loading={gatewayRestart.isPending}
              onPress={confirmGatewayRestart}
            >
              Restart gateway
            </Button>
          </ButtonGroup>
        }
      >
        <FormRow
          label="Status"
          value={roster.reachable ? "connected" : "reconnecting"}
        />
        <FormRow
          label="Host"
          value={
            session.connection ? new URL(session.connection.url).hostname : ""
          }
        />
        <FormRow label="Version" value={roster.gatewayVersion ?? "unknown"} />
        <FormRow
          label="Release channel"
          detail="Choose Stable releases or opt into prerelease builds."
          value={titleCaseChannel(gateway.data?.settings.channel)}
          trailing={
            gatewaySettings.isPending && gatewaySettings.variables?.channel ? (
              <ActivityIndicator size="small" />
            ) : undefined
          }
          onPress={gatewayControlsDisabled ? undefined : chooseReleaseChannel}
        />
        <SwitchRow
          label="Automatic updates"
          detail="Install new gateway releases automatically in the background."
          value={gateway.data?.settings.auto_update ?? false}
          disabled={gatewayControlsDisabled}
          onValueChange={(auto_update) =>
            gatewaySettings.mutate({ auto_update })
          }
        />
        <FormRow
          label="Public tunnel"
          value={gateway.data?.info.tunnel_url ? "active" : "unavailable"}
        />
      </FormSection>

      {roster.devices.length > 0 ? (
        <FormSection title="Devices">
          {roster.devices.map((device) => (
            <FormRow
              key={device.id}
              label={device.descriptor ?? "Unnamed device"}
              detail={deviceContextLine(device)}
              value={device.present ? "present now" : lastSeenLabel(device.lastSeen)}
            />
          ))}
          <SwitchRow
            label="Share device context"
            detail="Tell your agents each device's timezone and, when a phone shares it, its location, so they follow your travel. Off stops the reports and forgets what was stored."
            value={gateway.data?.settings.user_context ?? false}
            disabled={gatewayControlsDisabled}
            onValueChange={(user_context) =>
              gatewaySettings.mutate({ user_context })
            }
          />
        </FormSection>
      ) : null}

      {roster.managed ? (
        <FormSection
          title="Account"
          actions={
            <Button
              pill
              variant="card"
              onPress={() => void Linking.openURL("https://vesta.run/account")}
            >
              Manage account and billing
            </Button>
          }
        />
      ) : null}

      <FormSection
        title="Support"
        actions={
          <>
            <Button pill variant="card" onPress={() => router.push("/debug")}>
              Diagnostics
            </Button>
            <Button
              pill
              variant="card"
              onPress={() => router.push("/whats-new")}
            >
              What’s new
            </Button>
          </>
        }
      />

      <FormSection
        title="Other"
        actions={
          <Button
            pill
            variant="cardDanger"
            onPress={() => {
              Alert.alert(
                "Disconnect from Vesta?",
                "You can reconnect using your account or tunnel link.",
                [
                  { text: "Cancel", style: "cancel" },
                  {
                    text: "Disconnect",
                    style: "destructive",
                    onPress: () =>
                      void unregisterCurrentMobileDevice(session.api)
                        .catch(() => undefined)
                        .then(() => session.disconnect())
                        .then(() => router.replace("/connect")),
                  },
                ],
              );
            }}
          >
            Disconnect
          </Button>
        }
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { gap: 24 },
});
