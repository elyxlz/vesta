import { Alert, StyleSheet } from "react-native";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import {
  createBackup,
  deleteAgent,
  restartAgent,
  startAgent,
  stopAgent,
} from "@/api/endpoints";
import { AgentProvider, useAgent } from "@/agent/AgentProvider";
import { Screen } from "@/components/layout/Screen";
import { FormRow, FormSection } from "@/components/ui/Form";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

function AgentSettingsContent() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name, agent } = useAgent();
  const { colors } = usePreferences();
  const action = useMutation({
    mutationFn: async (
      operation: "start" | "stop" | "restart" | "backup" | "delete",
    ) => {
      if (operation === "start") await startAgent(api, name);
      if (operation === "stop") await stopAgent(api, name);
      if (operation === "restart") await restartAgent(api, name);
      if (operation === "backup") await createBackup(api, name);
      if (operation === "delete") await deleteAgent(api, name);
      return operation;
    },
    onSuccess: (operation) => {
      void queryClient.invalidateQueries({ queryKey: ["backups", name] });
      if (operation === "delete") router.replace("/");
    },
  });
  const open = (section: string) =>
    router.push({
      pathname: "/agent/[name]/details/[section]",
      params: { name, section },
    });
  const openPage = (page: "notifications" | "logs") =>
    router.push({
      pathname:
        page === "notifications"
          ? "/agent/[name]/notifications"
          : "/agent/[name]/logs",
      params: { name },
    });

  return (
    <Screen contentStyle={styles.content}>
      {action.error ? (
        <Text accessibilityRole="alert" style={{ color: colors.danger }}>
          {action.error instanceof Error
            ? action.error.message
            : "The action failed."}
        </Text>
      ) : null}
      <FormSection title="Agent">
        <FormRow
          label="General"
          detail="Identity and current status"
          icon="person-outline"
          onPress={() => open("general")}
        />
        <FormRow
          label="Provider and model"
          detail="Credentials, model, context, and usage"
          icon="sparkles-outline"
          onPress={() => open("provider")}
        />
        <FormRow
          label="Voice"
          detail="Live transcription and spoken replies"
          icon="mic-outline"
          onPress={() => open("voice")}
        />
      </FormSection>
      <FormSection title="Attention">
        <FormRow
          label="Notifications"
          detail="History and pending notifications"
          icon="notifications-outline"
          onPress={() => openPage("notifications")}
        />
        <FormRow
          label="Logs"
          detail="Live agent output"
          icon="terminal-outline"
          onPress={() => openPage("logs")}
        />
        <FormRow
          label="Notification rules"
          detail="Choose what interrupts the agent"
          icon="notifications-outline"
          onPress={() => open("notifications")}
        />
        <FormRow
          label="Files"
          detail="Memory, constitution, dreams, and skills"
          icon="folder-open-outline"
          onPress={() => open("files")}
        />
        <FormRow
          label="Host access"
          detail="Folders shared with this agent"
          icon="desktop-outline"
          onPress={() => open("host-access")}
        />
        <FormRow
          label="Backups"
          detail="Create, restore, and remove snapshots"
          icon="archive-outline"
          onPress={() => open("backups")}
        />
      </FormSection>
      <FormSection title="Actions">
        {agent?.status === "stopped" ? (
          <FormRow
            label="Start agent"
            icon="play-outline"
            onPress={() => action.mutate("start")}
          />
        ) : (
          <FormRow
            label="Stop agent"
            icon="stop-outline"
            onPress={() => action.mutate("stop")}
          />
        )}
        <FormRow
          label="Restart agent"
          icon="refresh-outline"
          onPress={() => action.mutate("restart")}
        />
        <FormRow
          label="Back up now"
          icon="cloud-upload-outline"
          onPress={() => action.mutate("backup")}
        />
      </FormSection>
      <FormSection>
        <FormRow
          label="Delete agent"
          icon="trash-outline"
          destructive
          onPress={() => {
            Alert.alert(
              `Delete ${name}?`,
              "This permanently deletes the agent and their local state.",
              [
                { text: "Cancel", style: "cancel" },
                {
                  text: "Delete",
                  style: "destructive",
                  onPress: () => action.mutate("delete"),
                },
              ],
            );
          }}
        />
      </FormSection>
    </Screen>
  );
}

export default function AgentSettingsScreen() {
  return (
    <AgentProvider>
      <AgentSettingsContent />
    </AgentProvider>
  );
}

const styles = StyleSheet.create({
  content: { paddingBottom: 80 },
});
