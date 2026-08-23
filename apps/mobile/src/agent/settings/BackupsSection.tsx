import { Alert, StyleSheet, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatSnapshotStamp, type BackupTimelinePoint } from "@vesta/core";
import {
  createBackup,
  deleteBackup,
  getAgentBackupSettings,
  listBackups,
  restoreBackup,
  setAgentBackupSettings,
} from "@/api/endpoints";
import { useAgent } from "@/agent/AgentProvider";
import { useAwaitedRoundTrip } from "@/agent/use-awaited-round-trip";
import { useToast } from "@/components/native-toast";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { FormRow, FormSection, SwitchRow } from "@/components/ui/Form";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";
import { radii } from "@/theme/layout";
import {
  backupTimeline,
  deletePrompt,
  NEWER_REFUSAL,
  restorePrompt,
  type ConfirmPrompt,
} from "./backups-model";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function confirm(prompt: ConfirmPrompt, run: () => void) {
  Alert.alert(prompt.title, prompt.body, [
    { text: "Cancel", style: "cancel" },
    {
      text: prompt.action,
      style: prompt.destructive ? "destructive" : "default",
      onPress: run,
    },
  ]);
}

function TimelinePoint({
  point,
  busy,
  restore,
  remove,
}: {
  point: BackupTimelinePoint;
  busy: boolean;
  restore: () => void;
  remove: () => void;
}) {
  const { colors } = usePreferences();
  const refused = point.eligibility === "newer";
  return (
    <Card>
      <Text style={[styles.pointTitle, { color: colors.text }]}>
        {formatSnapshotStamp(point.createdAt)}
      </Text>
      <View style={styles.meta}>
        <View
          style={[
            styles.badge,
            { backgroundColor: colors.elevated, borderColor: colors.border },
          ]}
        >
          <Text style={[styles.badgeLabel, { color: colors.secondaryText }]}>
            {point.label}
          </Text>
        </View>
        <Text style={[styles.pointMeta, { color: colors.secondaryText }]}>
          {formatBytes(point.size)}
        </Text>
      </View>
      {refused ? (
        <Text style={[styles.refusal, { color: colors.secondaryText }]}>
          {NEWER_REFUSAL}
        </Text>
      ) : null}
      <View style={styles.actions}>
        <View style={styles.action}>
          <Button
            variant="secondary"
            disabled={busy || refused}
            onPress={restore}
          >
            Restore
          </Button>
        </View>
        <View style={styles.action}>
          <Button variant="plain" disabled={busy} onPress={remove}>
            Delete
          </Button>
        </View>
      </View>
    </Card>
  );
}

export function BackupsSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name, agent } = useAgent();
  const { gatewayVersion } = useRoster();
  const { showError } = useToast();
  const { colors } = usePreferences();
  const backups = useQuery({
    queryKey: ["backups", name],
    queryFn: () => listBackups(api, name),
  });
  const operationTrip = useAwaitedRoundTrip(
    (agent?.operation ?? null) !== null,
  );
  const action = useMutation({
    mutationFn: async (
      operation:
        { type: "create" } | { type: "restore" | "delete"; id: string },
    ) => {
      if (operation.type === "create") await createBackup(api, name);
      if (operation.type === "restore")
        await restoreBackup(api, name, operation.id);
      if (operation.type === "delete")
        await deleteBackup(api, name, operation.id);
      return operation.type;
    },
    onSuccess: (type) => {
      void queryClient.invalidateQueries({ queryKey: ["backups", name] });
      if (type === "create" || type === "restore") operationTrip.start();
      if (type === "restore")
        Alert.alert(
          "Backup restored",
          `${name} is restarting with the selected snapshot.`,
        );
    },
    onError: (error) => showError(error, "The backup action failed"),
  });
  const backupSettings = useQuery({
    queryKey: ["backup-settings", name],
    queryFn: () => getAgentBackupSettings(api, name),
  });
  const toggleAuto = useMutation({
    mutationFn: (enabled: boolean) =>
      setAgentBackupSettings(api, name, enabled),
    onSuccess: (updated) => {
      queryClient.setQueryData(["backup-settings", name], updated);
    },
    onError: (error) => showError(error, "Could not update automatic backups"),
  });

  if (backups.isLoading) return <LoadingState label="Loading backups…" />;
  if (!backups.data) {
    return (
      <ErrorState
        message="Backups are unavailable."
        retry={() => void backups.refetch()}
      />
    );
  }

  // The gateway runs one operation per agent, so a restore or an update started elsewhere
  // disables these actions until it settles.
  const busy =
    action.isPending ||
    operationTrip.busy ||
    (agent?.operation ?? null) !== null;
  const points = backupTimeline(backups.data, gatewayVersion);

  return (
    <>
      <FormSection
        title="Automatic backups"
        footer="Snapshot this agent automatically on the schedule and before every update."
      >
        <SwitchRow
          label="Enabled"
          value={backupSettings.data?.enabled ?? false}
          disabled={backupSettings.isLoading || toggleAuto.isPending}
          onValueChange={(enabled) => toggleAuto.mutate(enabled)}
        />
      </FormSection>
      <FormSection
        title="Snapshots"
        footer="A backup captures the agent state before a risky change. Restoring replaces the current state and restarts the agent."
      >
        <FormRow
          label="Available backups"
          value={String(points.length)}
          icon="archive-outline"
        />
      </FormSection>
      <Button
        loading={action.isPending}
        disabled={busy}
        icon="cloud-upload-outline"
        onPress={() =>
          Alert.alert(
            "Back up now?",
            "The agent pauses briefly while the snapshot is captured.",
            [
              { text: "Cancel", style: "cancel" },
              {
                text: "Back up",
                onPress: () => action.mutate({ type: "create" }),
              },
            ],
          )
        }
      >
        Back up now
      </Button>
      {points.map((point) => (
        <TimelinePoint
          key={point.id}
          point={point}
          busy={busy}
          restore={() =>
            confirm(restorePrompt(point, name, gatewayVersion), () =>
              action.mutate({ type: "restore", id: point.id }),
            )
          }
          remove={() =>
            confirm(deletePrompt(point), () =>
              action.mutate({ type: "delete", id: point.id }),
            )
          }
        />
      ))}
      {points.length === 0 ? (
        <Text style={[styles.empty, { color: colors.secondaryText }]}>
          No backups yet.
        </Text>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  pointTitle: { fontSize: 16, fontWeight: "700" },
  pointMeta: { fontSize: 13 },
  meta: { flexDirection: "row", alignItems: "center", gap: 8 },
  badge: {
    borderRadius: radii.pill,
    borderCurve: "continuous",
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  badgeLabel: { fontSize: 12, fontWeight: "600" },
  refusal: { fontSize: 13 },
  actions: { flexDirection: "row", gap: 8 },
  action: { flex: 1 },
  empty: { textAlign: "center", paddingVertical: 30 },
});
