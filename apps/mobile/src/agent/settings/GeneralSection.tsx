import { StyleSheet, View } from "react-native";
import { useAgent } from "@/agent/AgentProvider";
import { AgentOrb } from "@/components/AgentOrb";
import { Card } from "@/components/ui/Card";
import { FormRow, FormSection } from "@/components/ui/Form";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

export function GeneralSection() {
  const { name, agent, socket } = useAgent();
  const { colors } = usePreferences();
  return (
    <>
      <Card glass>
        <View style={styles.hero}>
          <AgentOrb
            status={agent?.status ?? "not_found"}
            activityState={socket.agentState}
            size={84}
          />
          <View style={styles.identity}>
            <Text family="heading" style={[styles.name, { color: colors.text }]}>{name}</Text>
            <Text style={[styles.detail, { color: colors.secondaryText }]}>
              {socket.connected
                ? socket.agentState === "thinking"
                  ? "thinking"
                  : "online"
                : "reconnecting"}
            </Text>
          </View>
        </View>
      </Card>
      <FormSection title="Status">
        <FormRow label="Gateway state" value={agent?.status.replace(/_/g, " ") ?? "unavailable"} />
        <FormRow label="Activity" value={socket.agentState} />
        <FormRow
          label="Started"
          value={agent?.startedAt ? new Date(agent.startedAt).toLocaleString() : "not available"}
        />
        <FormRow label="Services" value={String(Object.keys(agent?.services ?? {}).length)} />
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
