import type { ReactNode } from "react";
import { StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import type {
  AgentActivityState,
  AgentOperation,
  AgentStatus,
} from "@vesta/core";
import { AgentOrb } from "@/components/AgentOrb";
import { AgentStatusBadge } from "@/components/AgentStatus";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

export const AGENT_IDENTITY_ORB_SIZE = 144;

export function AgentIdentityCard({
  name,
  status,
  activityState,
  operation = null,
  orb,
  style,
}: {
  name: string;
  status: AgentStatus;
  activityState: AgentActivityState;
  operation?: AgentOperation | null;
  orb?: ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  const { colors } = usePreferences();

  return (
    <View style={[styles.card, style]}>
      {orb ?? (
        <AgentOrb
          status={status}
          activityState={activityState}
          operation={operation}
          size={AGENT_IDENTITY_ORB_SIZE}
        />
      )}
      <View style={styles.details}>
        <AgentStatusBadge
          status={status}
          activityState={activityState}
          operation={operation}
          centered
        />
        <Text family="heading" style={[styles.name, { color: colors.text }]}>
          {name}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { alignItems: "center", gap: 32 },
  details: { alignItems: "center", gap: 6 },
  name: { fontSize: 38, fontWeight: "500", letterSpacing: -1 },
});
