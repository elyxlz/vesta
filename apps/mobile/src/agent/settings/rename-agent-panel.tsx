import { useState } from "react";
import { agentStatusKind, renameAgent } from "@vesta/core";
import { useMutation } from "@tanstack/react-query";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { useAgent } from "@/agent/AgentProvider";
import {
  agentRenameError,
  normalizeAgentName,
} from "@/agent/settings/agent-name";
import { Button } from "@/components/ui/Button";
import { Field, FormSection } from "@/components/ui/Form";
import { useSession } from "@/session/SessionProvider";

export function RenameAgentPanel() {
  const router = useRouter();
  const { name, agent } = useAgent();
  const { api } = useSession();
  const [proposedName, setProposedName] = useState(name);
  const [edited, setEdited] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const normalizedName = normalizeAgentName(proposedName);
  const validationError = agentRenameError(name, proposedName);
  const lifecycleBusy =
    agent === null ||
    agent.operation !== null ||
    agentStatusKind(agent.status) === "working";
  const rename = useMutation({
    mutationFn: () => renameAgent(api, name, normalizedName),
    onSuccess: (finalName) => {
      setProposedName(finalName);
      setEdited(false);
      setRequestError(null);
      router.replace({
        pathname: "/agent/[name]/settings",
        params: { name: finalName },
      });
    },
    onError: (error) => {
      setRequestError(
        error instanceof Error ? error.message : "The rename failed.",
      );
    },
  });
  const submitRename = () => {
    if (validationError || lifecycleBusy || rename.isPending) return;
    setRequestError(null);
    rename.mutate();
  };
  return (
    <FormSection
      footer={`Renaming restarts ${name}. Their memory, settings, and backups carry over.`}
      actions={
        <Button
          loading={rename.isPending}
          loadingLabel="Renaming…"
          disabled={Boolean(validationError) || lifecycleBusy}
          accessibilityLabel={`Rename ${name}`}
          onPress={submitRename}
        >
          Rename agent
        </Button>
      }
    >
      <View style={styles.renameForm}>
        <Field
          label="Name"
          description={
            normalizedName && normalizedName !== proposedName.trim()
              ? `This will be saved as ${normalizedName}.`
              : "Use letters, numbers, spaces, or hyphens."
          }
          error={
            requestError ??
            (edited ? (validationError ?? undefined) : undefined)
          }
          value={proposedName}
          editable={!rename.isPending && !lifecycleBusy}
          accessibilityLabel="New agent name"
          autoCapitalize="none"
          autoCorrect={false}
          returnKeyType="done"
          onChangeText={(value) => {
            setProposedName(value);
            setEdited(true);
            setRequestError(null);
          }}
          onSubmitEditing={submitRename}
        />
      </View>
    </FormSection>
  );
}

const styles = StyleSheet.create({
  renameForm: { paddingVertical: 10 },
});
