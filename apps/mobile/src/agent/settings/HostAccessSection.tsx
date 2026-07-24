import { useState } from "react";
import { Alert, StyleSheet, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAgentMounts,
  getHostFolderSuggestions,
  setAgentMounts,
} from "@/api/endpoints";
import type { HostMount } from "@/api/types";
import { useAgent } from "@/agent/AgentProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, FormRow, FormSection, SwitchRow } from "@/components/ui/Form";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

function folderName(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

export function HostAccessSection() {
  const queryClient = useQueryClient();
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const [adding, setAdding] = useState(false);
  const [hostPath, setHostPath] = useState("");
  const [containerPath, setContainerPath] = useState("");
  const [writable, setWritable] = useState(false);
  const mounts = useQuery({
    queryKey: ["mounts", name],
    queryFn: () => getAgentMounts(api, name),
  });
  const suggestions = useQuery({
    queryKey: ["host-folders"],
    queryFn: () => getHostFolderSuggestions(api),
    enabled: adding,
  });
  const save = useMutation({
    mutationFn: (next: HostMount[]) => setAgentMounts(api, name, next),
    onSuccess: (result) => {
      queryClient.setQueryData(["mounts", name], result.mounts);
      if (result.restartRequired) {
        Alert.alert("Restart needed", `${name} must restart before the new folder access takes effect.`);
      }
    },
  });

  if (mounts.isLoading) return <LoadingState label="Loading shared folders…" />;
  if (!mounts.data) {
    return <ErrorState message="Host access is unavailable." retry={() => void mounts.refetch()} />;
  }

  const update = (next: HostMount[]) => save.mutate(next);
  return (
    <>
      <FormSection
        title="Shared folders"
        footer="These paths live on the computer running the Vesta gateway, not on this phone. Folder grants take effect after the agent restarts."
      >
        {mounts.data.map((mount) => (
          <View key={mount.container_path} style={styles.mount}>
            <FormRow
              label={folderName(mount.host_path)}
              detail={mount.container_path === mount.host_path ? mount.host_path : `${mount.host_path} · seen at ${mount.container_path}`}
              icon="folder-open-outline"
            />
            <SwitchRow
              label="Allow editing"
              value={mount.writable}
              disabled={save.isPending}
              onValueChange={(value) => update(mounts.data.map((candidate) => candidate.container_path === mount.container_path ? { ...candidate, writable: value } : candidate))}
            />
            <Button
              variant="plain"
              disabled={save.isPending}
              onPress={() => Alert.alert("Remove folder access?", mount.host_path, [
                { text: "Cancel", style: "cancel" },
                { text: "Remove", style: "destructive", onPress: () => update(mounts.data.filter((candidate) => candidate.container_path !== mount.container_path)) },
              ])}
            >
              Remove access
            </Button>
          </View>
        ))}
        {mounts.data.length === 0 ? <FormRow label="No folders shared" icon="folder-outline" /> : null}
      </FormSection>

      {adding ? (
        <Card>
          {(suggestions.data ?? [])
            .filter((path) => !mounts.data.some((mount) => mount.host_path === path))
            .slice(0, 8)
            .map((path) => (
              <FormRow key={path} label={folderName(path)} detail={path} icon="folder-outline" onPress={() => setHostPath(path)} />
            ))}
          <Field label="Host path" description="Absolute path on the gateway computer." value={hostPath} onChangeText={setHostPath} autoCapitalize="none" autoCorrect={false} />
          <Field label="Path visible to the agent" description="Leave blank to use the same path." value={containerPath} onChangeText={setContainerPath} autoCapitalize="none" autoCorrect={false} />
          <SwitchRow label="Allow editing" value={writable} onValueChange={setWritable} />
          <Button
            loading={save.isPending}
            disabled={!hostPath.trim()}
            onPress={() => {
              const path = hostPath.trim();
              const next: HostMount = {
                host_path: path,
                container_path: containerPath.trim() || path,
                writable,
              };
              save.mutate([...mounts.data, next], {
                onSuccess: () => {
                  setAdding(false);
                  setHostPath("");
                  setContainerPath("");
                  setWritable(false);
                },
              });
            }}
          >
            Share folder
          </Button>
          <Button variant="secondary" onPress={() => setAdding(false)}>Cancel</Button>
        </Card>
      ) : (
        <Button icon="add" onPress={() => setAdding(true)}>Add a folder</Button>
      )}
      {save.error ? (
        <Text accessibilityRole="alert" style={{ color: colors.danger }}>
          {save.error instanceof Error ? save.error.message : "Could not update host access."}
        </Text>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  mount: { paddingVertical: 4 },
});
