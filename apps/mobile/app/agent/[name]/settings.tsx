import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { resolveProviderIdentity } from "@vesta/core";
import { Pressable, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import {
  createBackup,
  deleteAgent,
  fetchManifest,
  getProvider,
  restartAgent,
  startAgent,
  stopAgent,
} from "@/api/endpoints";
import { useAgent } from "@/agent/AgentProvider";
import { sectionTitle } from "@/agent/settings/sections-model";
import { AgentIdentityCard } from "@/components/agent-identity-card";
import { ProviderPill } from "@/components/ProviderPill";
import { Screen } from "@/components/layout/Screen";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { useToast } from "@/components/native-toast";
import { Button, ButtonGroup } from "@/components/ui/Button";
import { FormRow, FormSection, SwitchRow } from "@/components/ui/Form";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

function AgentSettingsContent() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name, agent, activityState } = useAgent();
  const preferences = usePreferences();
  const { showError } = useToast();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const provider = useQuery({
    queryKey: ["provider", name],
    queryFn: () => getProvider(api, name),
  });
  const manifest = useQuery({
    queryKey: ["manifest"],
    queryFn: () => fetchManifest(api),
  });
  const providerIdentity = resolveProviderIdentity(
    provider.data ?? null,
    manifest.data,
  );
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
    onError: (error) => showError(error, "The action failed"),
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
      <AgentIdentityCard
        name={name}
        status={agent?.status ?? "not_found"}
        activityState={activityState}
        operation={agent?.operation ?? null}
        booting={agent?.booting}
        caption={
          providerIdentity ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`${sectionTitle("provider")}, ${providerIdentity.providerName}`}
              hitSlop={6}
              onPress={() => open("provider")}
              style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}
            >
              <ProviderPill identity={providerIdentity} />
            </Pressable>
          ) : null
        }
        style={styles.identityCard}
      />
      <FormSection title="Agent">
        <FormRow
          label={sectionTitle("provider")}
          onPress={() => open("provider")}
        />
        <FormRow label={sectionTitle("voice")} onPress={() => open("voice")} />
      </FormSection>
      <FormSection title="Activity">
        <FormRow
          label="Notifications"
          onPress={() => openPage("notifications")}
        />
        <FormRow
          label={sectionTitle("notifications")}
          onPress={() => open("notifications")}
        />
        <FormRow label="Logs" onPress={() => openPage("logs")} />
      </FormSection>
      <FormSection title="Chat">
        <SwitchRow
          label="Natural pacing"
          detail="Let this agent's replies arrive with a more human rhythm."
          value={preferences.naturalChatPacingForAgent(name)}
          onValueChange={(value) =>
            void preferences.setNaturalChatPacingForAgent(name, value)
          }
        />
      </FormSection>
      <FormSection title="Pages">
        <SwitchRow
          label="Chat"
          detail="Messages with this agent."
          value={preferences.showChatPage}
          onValueChange={(value) =>
            void preferences.update({ showChatPage: value })
          }
        />
        <SwitchRow
          label="Dashboard"
          detail="Tasks, reminders, and more."
          value={preferences.showDashboardPage}
          onValueChange={(value) =>
            void preferences.update({ showDashboardPage: value })
          }
        />
        <SwitchRow
          label="Notifications"
          detail="Everything this agent was told."
          value={preferences.showNotificationsPage}
          onValueChange={(value) =>
            void preferences.update({ showNotificationsPage: value })
          }
        />
        <SwitchRow
          label="Logs"
          detail="Live output from this agent."
          value={preferences.showLogsPage}
          onValueChange={(value) =>
            void preferences.update({ showLogsPage: value })
          }
        />
      </FormSection>
      <FormSection title="Access">
        <FormRow label={sectionTitle("files")} onPress={() => open("files")} />
        <FormRow
          label={sectionTitle("host-access")}
          onPress={() => open("host-access")}
        />
      </FormSection>
      <FormSection
        title="Backups"
        actions={
          <ButtonGroup>
            <Button variant="cardGrouped" onPress={() => open("backups")}>
              Manage backups
            </Button>
            <Button
              variant="cardGrouped"
              disabled={action.isPending}
              loading={action.isPending && action.variables === "backup"}
              onPress={() => action.mutate("backup")}
            >
              Back up now
            </Button>
          </ButtonGroup>
        }
      />
      <FormSection
        actions={
          <ButtonGroup>
            <Button
              variant="cardGrouped"
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
              variant="cardGrouped"
              disabled={action.isPending}
              loading={action.isPending && action.variables === "restart"}
              onPress={() => action.mutate("restart")}
            >
              Restart agent
            </Button>
          </ButtonGroup>
        }
      />
      <FormSection
        actions={
          <Button
            pill
            variant="cardDanger"
            disabled={action.isPending}
            loading={action.isPending && action.variables === "delete"}
            onPress={() => {
              setConfirmingDelete(true);
            }}
          >
            Delete agent
          </Button>
        }
      />
      <ConfirmDialog
        visible={confirmingDelete}
        title={`Delete ${name}?`}
        message="This permanently deletes the agent and their local state."
        confirmLabel="Delete"
        destructive
        onConfirm={() => {
          setConfirmingDelete(false);
          action.mutate("delete");
        }}
        onDismiss={() => setConfirmingDelete(false)}
      />
    </Screen>
  );
}

export default function AgentSettingsScreen() {
  return (
    <>
      <NativeSheetCloseButton accessibilityLabel="Close agent settings" />
      <AgentSettingsContent />
    </>
  );
}

const styles = StyleSheet.create({
  content: { gap: 24, paddingBottom: 80 },
  identityCard: { paddingVertical: 20 },
});
