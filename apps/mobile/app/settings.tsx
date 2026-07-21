import { ActivityIndicator, Alert, Linking, StyleSheet } from "react-native";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { checkForGatewayUpdate, triggerGatewayRestart, triggerGatewayUpdate } from "@vesta/core";
import { fetchGatewayInfo, fetchGatewaySettings } from "@/api/endpoints";
import { Screen } from "@/components/layout/Screen";
import { FormRow, FormSection, SwitchRow } from "@/components/ui/Form";
import { unregisterCurrentMobileDevice } from "@/notifications/PushCoordinator";
import { usePreferences, type ThemePreference } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";

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
    Alert.alert("Restart gateway?", "Agent connections drop briefly and reconnect on their own.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Restart",
        onPress: () => gatewayRestart.mutate(),
      },
    ]);
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
    <Screen contentStyle={styles.content}>
      <FormSection title="Experience">
        <FormRow
          label="Appearance"
          icon="contrast-outline"
          value={preferences.theme}
          onPress={chooseTheme}
        />
      </FormSection>

      <FormSection title="Notifications">
        <SwitchRow
          label="Allow notifications"
          detail="Receive selected agent updates when the app is closed."
          icon="notifications-outline"
          value={preferences.remoteNotifications}
          onValueChange={(value) => void preferences.update({ remoteNotifications: value })}
        />
        <SwitchRow
          label="Chat replies"
          detail="Notify when an agent sends a completed chat reply."
          icon="chatbubble-outline"
          value={
            preferences.remoteNotifications && preferences.pushChatReplies
          }
          disabled={!preferences.remoteNotifications}
          onValueChange={(value) => void preferences.update({ pushChatReplies: value })}
        />
        <SwitchRow
          label="Message previews"
          detail="Show chat text on the lock screen. Off keeps messages private."
          icon="eye-outline"
          value={
            preferences.remoteNotifications &&
            preferences.pushChatReplies &&
            preferences.notificationPreviews
          }
          disabled={!preferences.remoteNotifications || !preferences.pushChatReplies}
          onValueChange={(value) => void preferences.update({ notificationPreviews: value })}
        />
        <SwitchRow
          label="Status changes"
          detail="Notify when an agent starts, stops, or changes availability."
          icon="pulse-outline"
          value={
            preferences.remoteNotifications && preferences.pushStatusChanges
          }
          disabled={!preferences.remoteNotifications}
          onValueChange={(value) => void preferences.update({ pushStatusChanges: value })}
        />
      </FormSection>

      <FormSection title="Gateway">
        <FormRow
          label="Status"
          icon="radio-outline"
          value={roster.reachable ? "connected" : "reconnecting"}
        />
        <FormRow label="Host" icon="cloud-outline" value={session.connection ? new URL(session.connection.url).hostname : ""} />
        <FormRow label="Version" icon="git-branch-outline" value={roster.gatewayVersion ?? "unknown"} />
        <FormRow label="Channel" icon="flask-outline" value={gateway.data?.settings.channel ?? "unknown"} />
        <FormRow
          label="Public tunnel"
          icon="globe-outline"
          value={gateway.data?.info.tunnel_url ? "active" : "unavailable"}
        />
        {gatewayUpdate.isPending ? (
          <FormRow
            label="Updating gateway"
            icon="arrow-up-circle-outline"
            trailing={
              <ActivityIndicator color={preferences.colors.interactive} />
            }
          />
        ) : updateCheck.isPending ? (
          <FormRow
            label="Checking for updates"
            icon="refresh-outline"
            trailing={
              <ActivityIndicator color={preferences.colors.interactive} />
            }
          />
        ) : updateAvailable ? (
          <FormRow
            label="Update available"
            icon="arrow-up-circle-outline"
            value={roster.latestVersion ?? "available"}
            onPress={confirmGatewayUpdate}
          />
        ) : updateCheck.isError ? (
          <FormRow
            label="Check failed"
            icon="alert-circle-outline"
            value="try again"
            onPress={() => updateCheck.mutate()}
          />
        ) : (
          <FormRow
            label="Check for updates"
            icon={updateCheck.isSuccess ? "checkmark-circle-outline" : "refresh-outline"}
            value={updateCheck.isSuccess ? "up to date" : undefined}
            onPress={() => updateCheck.mutate()}
          />
        )}
        <FormRow
          label="Restart gateway"
          icon="reload-outline"
          onPress={gatewayRestart.isPending ? undefined : confirmGatewayRestart}
          trailing={
            gatewayRestart.isPending ? (
              <ActivityIndicator color={preferences.colors.interactive} />
            ) : undefined
          }
        />
      </FormSection>

      {roster.managed ? (
        <FormSection title="Account">
          <FormRow
            label="Manage account and billing"
            icon="person-circle-outline"
            onPress={() => void Linking.openURL("https://vesta.run/account")}
          />
        </FormSection>
      ) : null}

      <FormSection title="Support">
        <FormRow label="Diagnostics" icon="pulse-outline" onPress={() => router.push("/debug")} />
        <FormRow
          label="What's new"
          icon="sparkles-outline"
          onPress={() => void Linking.openURL("https://github.com/elyxlz/vesta/releases")}
        />
      </FormSection>

      <FormSection title="Other">
        <FormRow
          label="Disconnect"
          icon="log-out-outline"
          destructiveIcon
          onPress={() => {
            Alert.alert("Disconnect from Vesta?", "You can reconnect using your account or tunnel link.", [
              { text: "Cancel", style: "cancel" },
              {
                text: "Disconnect",
                style: "destructive",
                onPress: () => void unregisterCurrentMobileDevice(session.api)
                  .catch(() => undefined)
                  .then(() => session.disconnect())
                  .then(() => router.replace("/connect")),
              },
            ]);
          }}
        />
      </FormSection>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { gap: 24 },
});
