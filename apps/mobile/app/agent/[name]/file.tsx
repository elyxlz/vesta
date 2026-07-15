import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Stack, useLocalSearchParams } from "expo-router";
import { readFile, writeFile } from "@/api/endpoints";
import { AgentProvider, useAgent } from "@/agent/AgentProvider";
import { Screen } from "@/components/layout/Screen";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { Text, TextInput } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

function fileName(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? "File";
}

function AgentFileContent() {
  const queryClient = useQueryClient();
  const parameters = useLocalSearchParams<{ path?: string }>();
  const path = typeof parameters.path === "string" ? parameters.path : "";
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const file = useQuery({
    queryKey: ["agent-file", name, path],
    queryFn: () => readFile(api, name, path),
    enabled: Boolean(path),
  });
  const draft = drafts[path] ?? file.data?.content ?? "";
  const setDraft = (content: string) => {
    setDrafts((current) => ({ ...current, [path]: content }));
  };
  const save = useMutation({
    mutationFn: () => writeFile(api, name, path, draft),
    onSuccess: () => {
      queryClient.setQueryData(["agent-file", name, path], file.data ? { ...file.data, content: draft } : file.data);
    },
  });

  if (!path) return <ErrorState message="No file path was provided." />;
  if (file.isLoading) return <LoadingState label="Opening file…" />;
  if (!file.data) {
    return <ErrorState message={file.error instanceof Error ? file.error.message : "The file could not be opened."} retry={() => void file.refetch()} />;
  }
  const editable = !file.data.readonly && file.data.encoding === "utf-8" && !file.data.is_dir;
  const changed = editable && draft !== file.data.content;
  return (
    <>
      <Stack.Screen options={{ title: fileName(path) }} />
      <Screen contentStyle={styles.content}>
        <Card>
          <Text selectable style={[styles.path, { color: colors.secondaryText }]}>{path}</Text>
          <Text style={[styles.meta, { color: colors.tertiaryText }]}>
            {file.data.readonly ? "Read only" : "Writable"} · {file.data.size.toLocaleString()} bytes
          </Text>
        </Card>
        {file.data.encoding === "base64" ? (
          <Text style={[styles.unsupported, { color: colors.secondaryText }]}>Binary files are not displayed on mobile.</Text>
        ) : (
          <TextInput
            family="mono"
            accessibilityLabel={`Contents of ${fileName(path)}`}
            value={draft}
            onChangeText={setDraft}
            editable={editable}
            multiline
            autoCapitalize="none"
            autoCorrect={false}
            textAlignVertical="top"
            selectionColor={colors.accent}
            style={[
              styles.editor,
              {
                backgroundColor: colors.input,
                borderColor: colors.border,
                color: colors.text,
              },
            ]}
          />
        )}
        {editable ? (
          <View style={styles.buttons}>
            <Button
              variant="secondary"
              disabled={!changed || save.isPending}
              onPress={() => setDraft(file.data.content)}
            >
              Revert
            </Button>
            <Button loading={save.isPending} disabled={!changed} onPress={() => save.mutate()}>
              Save file
            </Button>
          </View>
        ) : null}
        {save.error ? (
          <Text accessibilityRole="alert" style={{ color: colors.danger }}>
            {save.error instanceof Error ? save.error.message : "The file could not be saved."}
          </Text>
        ) : null}
      </Screen>
    </>
  );
}

export default function AgentFileScreen() {
  return (
    <AgentProvider>
      <AgentFileContent />
    </AgentProvider>
  );
}

const styles = StyleSheet.create({
  content: { flexGrow: 1 },
  path: { fontSize: 12, lineHeight: 17 },
  meta: { fontSize: 12 },
  editor: {
    minHeight: 420,
    flexGrow: 1,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 18,
    padding: 14,
    fontSize: 13,
    lineHeight: 19,
  },
  unsupported: { textAlign: "center", padding: 30 },
  buttons: { gap: 8 },
});
