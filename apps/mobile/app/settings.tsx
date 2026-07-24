import { Alert, Linking, StyleSheet } from "react-native";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Stack, useRouter } from "expo-router";
import {
  checkForGatewayUpdate,
  triggerGatewayRestart,
  triggerGatewayUpdate,
} from "@vesta/core";
import { fetchGatewayInfo, fetchGatewaySettings } from "@/api/endpoints";
import { Screen } from "@/components/layout/Screen";
import { Button } from "@/components/ui/Button";
import { FormRow, FormSection, SwitchRow } from "@/components/ui/Form";
import { unregisterCurrentMobileDevice } from "@/notifications/PushCoordinator";
import {
  usePreferences,
  type ThemePreference,
} from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";

const IS_IOS = process.env.EXPO_OS === "ios";
const appearanceValueIcons = {
  light: "sunny-outline",
  dark: "moon-outline",
} as const;

export default function SettingsScreen() {
  const router = useRouter();
  const session = useSession();
  const roster = useRoster();
  const preferences = usePreferences();
  const gateway = useQuery({
    queryKey: ["gateway", session.connection?.url],
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
  });
  const gatewayUpdate = useMutation({
    mutationFn: () => triggerGatewayUpdate(session.api),
  });
  // A restart drops every agent connection briefly like an update; the live socket self-heals on
  // its own once the gateway comes back, so nothing forces a reconnect here.
  const gatewayRestart = useMutation({
    mutationFn: () => triggerGatewayRestart(session.api),
  });
  const updateAvailable = roster.updateAvailable;
  const resolvedAppearance =
    preferences.theme === "system"
      ? preferences.dark
        ? "dark"
        : "light"
      : preferences.theme;
  const appearanceValueIcon = appearanceValueIcons[resolvedAppearance];

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

  return (
    <>
      <Screen contentStyle={styles.content}>
        <FormSection title="Experience">
          <FormRow
            label="Appearance"
            detail="Use the system setting or choose light or dark."
            onPress={chooseTheme}
            valueIcon={appearanceValueIcon}
            valueIconLabel={`${resolvedAppearance} appearance${
              preferences.theme === "system" ? " from system setting" : ""
            }`}
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
            value={
              preferences.remoteNotifications && preferences.pushChatReplies
            }
            disabled={!preferences.remoteNotifications}
            onValueChange={(value) =>
              void preferences.update({ pushChatReplies: value })
            }
          />
          <SwitchRow
            label="Message previews"
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
            <>
              <Button
                pill
                variant="card"
                loading={gatewayUpdate.isPending || updateCheck.isPending}
                onPress={
                  updateAvailable
                    ? confirmGatewayUpdate
                    : () => updateCheck.mutate()
                }
              >
                {updateAvailable
                  ? "Update gateway"
                  : updateCheck.isError
                    ? "Retry update check"
                    : updateCheck.isSuccess
                      ? "Check again for updates"
                      : "Check for updates"}
              </Button>
              <Button
                pill
                variant="card"
                loading={gatewayRestart.isPending}
                onPress={confirmGatewayRestart}
              >
                Restart gateway
              </Button>
            </>
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
            label="Channel"
            value={gateway.data?.settings.channel ?? "unknown"}
          />
          <FormRow
            label="Public tunnel"
            value={gateway.data?.info.tunnel_url ? "active" : "unavailable"}
          />
        </FormSection>

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
                onPress={() =>
                  void Linking.openURL(
                    "https://github.com/elyxlz/vesta/releases",
                  )
                }
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
      <Stack.Toolbar placement="left">
        <Stack.Toolbar.Button
          accessibilityLabel="Close settings"
          icon={IS_IOS ? "xmark" : undefined}
          separateBackground
          tintColor={preferences.colors.text}
          onPress={() => router.back()}
        >
          {IS_IOS ? undefined : "Close"}
        </Stack.Toolbar.Button>
      </Stack.Toolbar>
    </>
  );
}

const styles = StyleSheet.create({
  content: { gap: 24 },
});
