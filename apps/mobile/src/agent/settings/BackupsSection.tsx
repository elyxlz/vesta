import { Alert, StyleSheet, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createBackup,
  deleteBackup,
  listBackups,
  restoreBackup,
} from "@/api/endpoints";
import type { BackupInfo } from "@/api/types";
import { useAgent } from "@/agent/AgentProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { FormRow, FormSection } from "@/components/ui/Form";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function BackupCard({
  backup,
  busy,
  restore,
  remove,
}: {
  backup: BackupInfo;
  busy: boolean;
  restore: () => void;
  remove: () => void;
}) {
  const { colors } = usePreferences();
  return (
    <Card>
      <Text style={[styles.backupTitle, { color: colors.text }]}>
        {new Date(backup.created_at).toLocaleString()}
      </Text>
      <Text style={[styles.backupMeta, { color: colors.secondaryText }]}>
        {backup.backup_type} · {formatBytes(backup.size)}
      </Text>
      <View style={styles.actions}>
        <View style={styles.action}><Button variant="secondary" disabled={busy} onPress={restore}>Restore</Button></View>
        <View style={styles.action}><Button variant="plain" disabled={busy} onPress={remove}>Delete</Button></View>
      </View>
    </Card>
  );
}

export function BackupsSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const backups = useQuery({
    queryKey: ["backups", name],
    queryFn: () => listBackups(api, name),
  });
  const action = useMutation({
    mutationFn: async (operation: { type: "create" } | { type: "restore" | "delete"; id: string }) => {
      if (operation.type === "create") await createBackup(api, name);
      if (operation.type === "restore") await restoreBackup(api, name, operation.id);
      if (operation.type === "delete") await deleteBackup(api, name, operation.id);
      return operation.type;
    },
    onSuccess: (type) => {
      void queryClient.invalidateQueries({ queryKey: ["backups", name] });
      if (type === "restore") Alert.alert("Backup restored", `${name} is restarting with the selected snapshot.`);
    },
  });

  if (backups.isLoading) return <LoadingState label="Loading backups…" />;
  if (!backups.data) {
    return <ErrorState message="Backups are unavailable." retry={() => void backups.refetch()} />;
  }

  return (
    <>
      <FormSection title="Snapshots" footer="A backup captures the agent state before a risky change. Restoring replaces the current state and restarts the agent.">
        <FormRow label="Available backups" value={String(backups.data.length)} icon="archive-outline" />
      </FormSection>
      <Button loading={action.isPending} icon="cloud-upload-outline" onPress={() => action.mutate({ type: "create" })}>Back up now</Button>
      {[...backups.data]
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map((backup) => (
          <BackupCard
            key={backup.id}
            backup={backup}
            busy={action.isPending}
            restore={() => Alert.alert("Restore this backup?", "Current agent state will be replaced.", [
              { text: "Cancel", style: "cancel" },
              { text: "Restore", onPress: () => action.mutate({ type: "restore", id: backup.id }) },
            ])}
            remove={() => Alert.alert("Delete this backup?", "This snapshot cannot be recovered.", [
              { text: "Cancel", style: "cancel" },
              { text: "Delete", style: "destructive", onPress: () => action.mutate({ type: "delete", id: backup.id }) },
            ])}
          />
        ))}
      {backups.data.length === 0 ? (
        <Text style={[styles.empty, { color: colors.secondaryText }]}>No backups yet.</Text>
      ) : null}
      {action.error ? (
        <Text accessibilityRole="alert" style={{ color: colors.danger }}>
          {action.error instanceof Error ? action.error.message : "The backup action failed."}
        </Text>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  backupTitle: { fontSize: 16, fontWeight: "700" },
  backupMeta: { fontSize: 13 },
  actions: { flexDirection: "row", gap: 8 },
  action: { flex: 1 },
  empty: { textAlign: "center", paddingVertical: 30 },
});
