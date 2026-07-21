import type { ReactNode } from "react";
import { StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";
import type { AgentActivityState, AgentStatus } from "@vesta/core";
import { AgentOrb } from "@/components/AgentOrb";
import { AgentStatusBadge } from "@/components/AgentStatus";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

export const AGENT_IDENTITY_ORB_SIZE = 144;

export function AgentIdentityCard({
  name,
  status,
  activityState,
  orb,
  style,
}: {
  name: string;
  status: AgentStatus;
  activityState: AgentActivityState;
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
          size={AGENT_IDENTITY_ORB_SIZE}
        />
      )}
      <View style={styles.details}>
        <AgentStatusBadge status={status} centered />
        <Text
          family="heading"
          style={[styles.name, { color: colors.text }]}
        >
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
