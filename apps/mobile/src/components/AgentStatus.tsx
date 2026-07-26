import { StyleSheet, View } from "react-native";
import type { AgentActivityState, AgentStatus } from "@vesta/core";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { Text } from "@/components/ui/Typography";

const STATUS_LABELS: Record<AgentStatus, string> = {
  alive: "online",
  starting: "starting",
  setting_up: "setting up",
  not_authenticated: "sign-in needed",
  unprovisioned: "setup needed",
  restarting: "restarting",
  rebuilding: "rebuilding",
  stopped: "stopped",
  dead: "offline",
  not_found: "unavailable",
};

export function AgentStatusBadge({
  status,
  activityState = "idle",
  centered = false,
}: {
  status: AgentStatus;
  activityState?: AgentActivityState;
  centered?: boolean;
}) {
  const { colors } = usePreferences();
  const active = status === "alive";
  const thinking = active && activityState === "thinking";
  const attention =
    status === "not_authenticated" || status === "unprovisioned";
  const color = thinking
    ? colors.warning
    : active
      ? colors.success
      : attention
        ? colors.warning
        : colors.tertiaryText;
  const label = thinking ? "thinking" : STATUS_LABELS[status];
  return (
    <View
      style={[
        styles.badge,
        centered ? styles.centered : null,
        { backgroundColor: `${color}20` },
      ]}
    >
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={[styles.label, { color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderRadius: 999,
  },
  centered: { alignSelf: "center" },
  dot: { width: 6, height: 6, borderRadius: 3 },
  label: { fontSize: 12, fontWeight: "700" },
});
