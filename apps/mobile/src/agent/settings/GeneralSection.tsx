import { useState } from "react";
import {
  agentStatusKind,
  resolveProviderIdentity,
  getProvider,
  renameAgent,
} from "@vesta/core";
import { useMutation, useQuery } from "@tanstack/react-query";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { useAgent } from "@/agent/AgentProvider";
import {
  agentRenameError,
  normalizeAgentName,
} from "@/agent/settings/agent-name";
import { AgentOrb } from "@/components/AgentOrb";
import { ProviderPill } from "@/components/ProviderPill";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, FormRow, FormSection } from "@/components/ui/Form";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

export function GeneralSection() {
  const router = useRouter();
  const { name, agent, activityState, socket } = useAgent();
  const { colors } = usePreferences();
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
        pathname: "/agent/[name]/details/[section]",
        params: { name: finalName, section: "general" },
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
  const providerResource = useQuery({
    queryKey: ["provider", name],
    queryFn: () => getProvider(api, name),
  });
  const providerIdentity = resolveProviderIdentity(
    providerResource.data?.provider ?? null,
    providerResource.data?.catalog,
  );
  return (
    <>
      <Card glass>
        <View style={styles.hero}>
          <AgentOrb
            status={agent?.status ?? "not_found"}
            activityState={activityState}
            booting={agent?.booting}
            rateLimited={agent?.rateLimited ?? null}
            size={84}
          />
          <View style={styles.identity}>
            <Text
              family="heading"
              style={[styles.name, { color: colors.text }]}
            >
              {name}
            </Text>
            <Text style={[styles.detail, { color: colors.secondaryText }]}>
              {socket.connected
                ? activityState === "thinking"
                  ? "thinking"
                  : "online"
                : "reconnecting"}
            </Text>
            {providerIdentity && <ProviderPill identity={providerIdentity} />}
          </View>
        </View>
      </Card>
      <FormSection
        title="Identity"
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
      <FormSection title="Status">
        <FormRow
          label="Gateway state"
          value={agent?.status.replace(/_/g, " ") ?? "unavailable"}
        />
        <FormRow label="Activity" value={activityState} />
        <FormRow
          label="Started"
          value={
            agent?.startedAt
              ? new Date(agent.startedAt).toLocaleString()
              : "not available"
          }
        />
        <FormRow
          label="Services"
          value={String(Object.keys(agent?.services ?? {}).length)}
        />
      </FormSection>
    </>
  );
}

const styles = StyleSheet.create({
  hero: { flexDirection: "row", alignItems: "center", gap: 18 },
  identity: { flex: 1, gap: 4 },
  name: { fontSize: 28, fontWeight: "500" },
  detail: { fontSize: 15 },
  renameForm: { paddingVertical: 10 },
});
