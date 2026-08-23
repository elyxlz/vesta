import { StyleSheet, View } from "react-native";
import { SkeletonPulse } from "@/components/ui/skeleton-pulse";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

const PLACEHOLDER_ROWS = [
  { side: "agent", width: "70%", height: 64 },
  { side: "user", width: "52%", height: 42 },
  { side: "agent", width: "46%", height: 42 },
  { side: "user", width: "64%", height: 58 },
  { side: "agent", width: "76%", height: 78 },
  { side: "user", width: "42%", height: 42 },
  { side: "agent", width: "58%", height: 54 },
  { side: "user", width: "68%", height: 44 },
  { side: "agent", width: "40%", height: 38 },
  { side: "user", width: "55%", height: 32 },
  { side: "agent", width: "62%", height: 38 },
] as const;

export function ChatLoadingSkeleton() {
  const { colors } = usePreferences();

  return (
    <SkeletonPulse label="Loading conversation" style={styles.skeleton}>
      <View style={styles.stack}>
        {PLACEHOLDER_ROWS.map((row, index) => (
          <View
            key={index}
            style={[
              styles.bubble,
              row.side === "user" ? styles.userBubble : styles.agentBubble,
              {
                width: row.width,
                height: row.height,
                backgroundColor:
                  row.side === "user" ? colors.accent : colors.card,
                borderColor:
                  row.side === "agent" ? colors.border : "transparent",
              },
            ]}
          />
        ))}
      </View>
    </SkeletonPulse>
  );
}

const styles = StyleSheet.create({
  skeleton: {
    flex: 1,
    overflow: "hidden",
  },
  stack: {
    position: "absolute",
    right: 8,
    bottom: 0,
    left: 8,
    gap: 10,
  },
  bubble: {
    borderRadius: radii.bubble,
    borderCurve: "continuous",
  },
  agentBubble: {
    alignSelf: "flex-start",
    borderWidth: StyleSheet.hairlineWidth,
  },
  userBubble: { alignSelf: "flex-end" },
});
