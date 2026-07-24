import { Alert, StyleSheet } from "react-native";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Stack, useRouter } from "expo-router";
import {
  createBackup,
  deleteAgent,
  restartAgent,
  startAgent,
  stopAgent,
} from "@/api/endpoints";
import { useAgent } from "@/agent/AgentProvider";
import { AgentPagesSettingsSection } from "@/components/AgentPagesSettingsSection";
import { AgentIdentityCard } from "@/components/agent-identity-card";
import { Screen } from "@/components/layout/Screen";
import { Button } from "@/components/ui/Button";
import { FormSection, SwitchRow } from "@/components/ui/Form";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

const IS_IOS = process.env.EXPO_OS === "ios";

function AgentSettingsContent() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name, agent, socket } = useAgent();
  const preferences = usePreferences();
  const { colors } = preferences;
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
    <>
      <Screen contentStyle={styles.content}>
        <AgentIdentityCard
          name={name}
          status={agent?.status ?? "not_found"}
          activityState={socket.agentState}
          style={styles.identityCard}
        />
        {action.error ? (
          <Text accessibilityRole="alert" style={{ color: colors.danger }}>
            {action.error instanceof Error
              ? action.error.message
              : "The action failed."}
          </Text>
        ) : null}
        <FormSection
          title="Agent"
          actions={
            <>
              <Button pill variant="card" onPress={() => open("provider")}>
                Provider and model
              </Button>
              <Button pill variant="card" onPress={() => open("voice")}>
                Voice
              </Button>
            </>
          }
        >
          <SwitchRow
            label="Natural chat pacing"
            detail="Let this agent's replies arrive with a more human rhythm."
            value={preferences.naturalChatPacingForAgent(name)}
            onValueChange={(value) =>
              void preferences.setNaturalChatPacingForAgent(name, value)
            }
          />
        </FormSection>
        <AgentPagesSettingsSection />
        <FormSection
          title="Attention"
          actions={
            <>
              <Button
                pill
                variant="card"
                onPress={() => openPage("notifications")}
              >
                Notifications
              </Button>
              <Button pill variant="card" onPress={() => openPage("logs")}>
                Logs
              </Button>
              <Button pill variant="card" onPress={() => open("notifications")}>
                Notification rules
              </Button>
              <Button pill variant="card" onPress={() => open("files")}>
                Files
              </Button>
              <Button pill variant="card" onPress={() => open("host-access")}>
                Host access
              </Button>
              <Button pill variant="card" onPress={() => open("backups")}>
                Backups
              </Button>
            </>
          }
        />
        <FormSection
          title="Actions"
          actions={
            <>
              <Button
                pill
                variant="card"
                disabled={action.isPending}
                loading={
                  action.isPending &&
                  (action.variables === "start" || action.variables === "stop")
                }
                onPress={() =>
                  action.mutate(agent?.status === "stopped" ? "start" : "stop")
                }
              >
                {agent?.status === "stopped" ? "Start agent" : "Stop agent"}
              </Button>
              <Button
                pill
                variant="card"
                disabled={action.isPending}
                loading={action.isPending && action.variables === "restart"}
                onPress={() => action.mutate("restart")}
              >
                Restart agent
              </Button>
              <Button
                pill
                variant="card"
                disabled={action.isPending}
                loading={action.isPending && action.variables === "backup"}
                onPress={() => action.mutate("backup")}
              >
                Back up now
              </Button>
            </>
          }
        />
        <FormSection
          title="Danger zone"
          actions={
            <Button
              pill
              variant="cardDanger"
              disabled={action.isPending}
              loading={action.isPending && action.variables === "delete"}
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
            >
              Delete agent
            </Button>
          }
        />
      </Screen>
      <Stack.Toolbar placement="left">
        <Stack.Toolbar.Button
          accessibilityLabel="Close agent settings"
          icon={IS_IOS ? "xmark" : undefined}
          separateBackground
          tintColor={colors.text}
          onPress={() => router.back()}
        >
          {IS_IOS ? undefined : "Close"}
        </Stack.Toolbar.Button>
      </Stack.Toolbar>
    </>
  );
}

export default function AgentSettingsScreen() {
  return <AgentSettingsContent />;
}

const styles = StyleSheet.create({
  content: { paddingBottom: 80 },
  identityCard: { paddingVertical: 20 },
});
