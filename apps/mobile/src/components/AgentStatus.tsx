import { use } from "react";
import { StyleSheet, View } from "react-native";
import {
  agentNeedsUser,
  agentVisualStatus,
  type AgentActivityState,
  type AgentOperation,
  type AgentStatus,
  type RateLimitedInfo,
} from "@vesta/core";
import { useAgentRequest } from "@vesta/core/react";
import { ControllerContext } from "@/controller/context";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { Text } from "@/components/ui/Typography";

export function AgentStatusBadge({
  name,
  status,
  activityState = "idle",
  operation = null,
  booting = false,
  rateLimited = null,
  centered = false,
}: {
  // The roster agent, so this client's own in-flight request overlays the badge.
  name?: string;
  status: AgentStatus;
  activityState?: AgentActivityState;
  operation?: AgentOperation | null;
  booting?: boolean;
  rateLimited?: RateLimitedInfo | null;
  centered?: boolean;
}) {
  const { colors } = usePreferences();
  const { request } = useAgentRequest(use(ControllerContext), name ?? null);
  const { label, orbState } = agentVisualStatus(
    { status, operation, booting, rateLimited },
    request,
    activityState,
  );
  const active = status === "alive" && !booting;
  const limited = active && operation === null && rateLimited != null;
  const thinking = active && !limited && activityState === "thinking";
  const attention = operation === null && agentNeedsUser(status);
  const color =
    request !== "idle"
      ? orbState === "deleting"
        ? colors.danger
        : colors.tertiaryText
      : limited || thinking
        ? colors.warning
        : active
          ? colors.success
          : attention
            ? colors.warning
            : colors.tertiaryText;
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
    borderCurve: "continuous",
  },
  centered: { alignSelf: "center" },
  dot: { width: 6, height: 6, borderRadius: 3 },
  label: { fontSize: 12, fontWeight: "700" },
});
