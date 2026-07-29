import { resolveProviderIdentity } from "@vesta/core";
import { useQuery } from "@tanstack/react-query";
import { StyleSheet, View } from "react-native";
import { fetchManifest, getProvider } from "@/api/endpoints";
import { useAgent } from "@/agent/AgentProvider";
import { AgentOrb } from "@/components/AgentOrb";
import { ProviderPill } from "@/components/ProviderPill";
import { Card } from "@/components/ui/Card";
import { FormRow, FormSection } from "@/components/ui/Form";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

export function GeneralSection() {
  const { name, agent, activityState, socket } = useAgent();
  const { colors } = usePreferences();
  const { api } = useSession();
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
  return (
    <>
      <Card glass>
        <View style={styles.hero}>
          <AgentOrb
            status={agent?.status ?? "not_found"}
            activityState={activityState}
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
});
