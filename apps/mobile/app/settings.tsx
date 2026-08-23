import { useState } from "react";
import { Linking, StyleSheet, View } from "react-native";
import { LoadingSpinner } from "@/components/loading-spinner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import { ConfirmDialog } from "@/components/confirm-dialog";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";
import { useToast } from "@/components/native-toast";
import { OptionPicker } from "@/components/option-picker";
import type { OptionPickerOption } from "@/components/option-picker.types";
import {
  SegmentedControl,
  type SegmentedOption,
} from "@/components/ui/segmented-control";
import { AppearancePreview } from "@/components/appearance-preview";
import { Button, ButtonGroup } from "@/components/ui/Button";
import { FormRow, FormSection, SwitchRow } from "@/components/ui/Form";
import { requestLocationSharing } from "@/device-context/location-consent";
import { unregisterCurrentMobileDevice } from "@/notifications/PushCoordinator";
import {
  usePreferences,
  type ThemePreference,
} from "@/preferences/PreferencesProvider";
import { usePrivacy } from "@/privacy/privacy-provider";
import { lastSeenLabel, titleCaseChannel } from "@/session/device-label-model";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";

const themeOptions: readonly SegmentedOption<ThemePreference>[] = [
  {
    value: "system",
    label: "System",
    preview: <AppearancePreview theme="system" />,
  },
  {
    value: "light",
    label: "Light",
    preview: <AppearancePreview theme="light" />,
  },
  { value: "dark", label: "Dark", preview: <AppearancePreview theme="dark" /> },
];
const channelOptions: readonly OptionPickerOption<ReleaseChannel>[] = [
  { value: "stable", label: "Stable" },
  { value: "beta", label: "Beta" },
];
type ActivePicker = "channel" | null;
type ActiveConfirm = "update" | "restart" | "disconnect" | null;
type GatewayQueryData = {
  info: GatewayInfo;
  settings: GatewaySettings;
};

// The device's reported place and zone, falling back to the gateway's IP-derived location.
function deviceContextLine(device: DeviceInfo): string | undefined {
  const place = device.position?.place;
  const placeLabel =
    place && (place.city ?? place.region)
      ? [place.city ?? place.region, place.country].filter(Boolean).join(", ")
      : undefined;
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
  const [activePicker, setActivePicker] = useState<ActivePicker>(null);
  const [activeConfirm, setActiveConfirm] = useState<ActiveConfirm>(null);
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
      patch: Partial<Pick<GatewaySettings, "auto_update" | "channel">>,
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
  const gatewayControlsDisabled =
    !gateway.data || !roster.reachable || gatewaySettings.isPending;

  const confirmGatewayUpdate = () => {
    setActiveConfirm("update");
  };

  const confirmGatewayRestart = () => {
    setActiveConfirm("restart");
  };

  const selectTheme = (theme: ThemePreference) => {
    void preferences.update({ theme });
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
      if (enabled && !(await requestLocationSharing())) {
        showError(
          new Error("Allow location for Vesta in system settings to share it."),
          "Location is not allowed",
        );
        return;
      }
      await preferences.update({ shareLocation: enabled });
    } catch (error) {
      showError(error, "Location sharing is unavailable");
    }
  };

  const selectReleaseChannel = (channel: ReleaseChannel) => {
    setActivePicker(null);
    if (channel !== gateway.data?.settings.channel) {
      gatewaySettings.mutate({ channel });
    }
  };

  return (
    <>
      <SheetChrome grabber title="Settings" closeLabel="Close settings" />
      <Screen contentStyle={styles.content}>
        <NativeSheetCloseButton
          accessibilityLabel="Close settings"
          visibleFromDetentIndex={1}
        />
        <OptionPicker
          visible={activePicker === "channel"}
          title="Release channel"
          message="Beta gives you new features early. Stable waits until they are ready for everyone."
          options={channelOptions}
          selectedValue={gateway.data?.settings.channel}
          onSelect={selectReleaseChannel}
          onDismiss={() => setActivePicker(null)}
        />
        <ConfirmDialog
          visible={activeConfirm === "update"}
          title="Update gateway?"
          message="Agents will briefly restart."
          confirmLabel="Update"
          onConfirm={() => {
            setActiveConfirm(null);
            gatewayUpdate.mutate();
          }}
          onDismiss={() => setActiveConfirm(null)}
        />
        <ConfirmDialog
          visible={activeConfirm === "restart"}
          title="Restart gateway?"
          message="Agent connections drop briefly and reconnect on their own."
          confirmLabel="Restart"
          onConfirm={() => {
            setActiveConfirm(null);
            gatewayRestart.mutate();
          }}
          onDismiss={() => setActiveConfirm(null)}
        />
        <ConfirmDialog
          visible={activeConfirm === "disconnect"}
          title="Disconnect from Vesta?"
          message="You can reconnect using your account or tunnel link."
          confirmLabel="Disconnect"
          destructive
          onConfirm={() => {
            setActiveConfirm(null);
            void unregisterCurrentMobileDevice(session.api)
              .catch(() => undefined)
              .then(() => session.disconnect())
              .then(() => router.replace("/connect"));
          }}
          onDismiss={() => setActiveConfirm(null)}
        />
        <FormSection title="Appearance">
          <View style={styles.appearanceRow}>
            <SegmentedControl
              accessibilityLabel="Appearance"
              options={themeOptions}
              selectedValue={preferences.theme}
              onSelect={selectTheme}
            />
          </View>
        </FormSection>

        <FormSection title="Privacy">
          <SwitchRow
            label="App Lock"
            detail={`Require ${privacy.authenticationName} when returning to Vesta.`}
            value={privacy.appLockEnabled}
            disabled={!privacy.hydrated || privacySaving}
            onValueChange={(value) => void changeAppLock(value)}
          />
          <SwitchRow
            label="Share device location"
            detail="Let Vesta know where you are, to help you wherever you go."
            value={preferences.shareLocation}
            onValueChange={(value) => void changeShareLocation(value)}
          />
        </FormSection>

        <FormSection title="Notifications">
          <SwitchRow
            label="Allow notifications"
            detail="Hear from Vesta even when the app is closed."
            value={preferences.remoteNotifications}
            onValueChange={(value) =>
              void preferences.update({ remoteNotifications: value })
            }
          />
          <SwitchRow
            label="Chat replies"
            detail="Get notified when Vesta replies."
            value={
              preferences.remoteNotifications && preferences.pushChatReplies
            }
            disabled={!preferences.remoteNotifications}
            onValueChange={(value) =>
              void preferences.update({ pushChatReplies: value })
            }
          />
          <SwitchRow
            label="Show message content"
            detail="Preview the message on your lock screen."
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
              gatewaySettings.isPending &&
              gatewaySettings.variables?.channel ? (
                <LoadingSpinner size="small" />
              ) : undefined
            }
            onPress={
              gatewayControlsDisabled
                ? undefined
                : () => setActivePicker("channel")
            }
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
        </FormSection>

        {roster.devices.length > 0 ? (
          <FormSection title="Devices">
            {roster.devices.map((device) => (
              <FormRow
                key={device.id}
                label={device.descriptor ?? "Unnamed device"}
                detail={deviceContextLine(device)}
                value={
                  device.present
                    ? "present now"
                    : lastSeenLabel(device.lastSeen)
                }
              />
            ))}
          </FormSection>
        ) : null}

        {roster.managed ? (
          <FormSection
            title="Account"
            actions={
              <Button
                pill
                variant="card"
                onPress={() =>
                  void Linking.openURL("https://vesta.run/account")
                }
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
                setActiveConfirm("disconnect");
              }}
            >
              Disconnect
            </Button>
          }
        />
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  appearanceRow: { paddingVertical: 10 },
  content: { gap: 24 },
});
