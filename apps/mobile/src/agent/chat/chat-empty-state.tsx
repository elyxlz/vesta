import { StyleSheet, View } from "react-native";
import Reanimated, {
  useAnimatedStyle,
  type SharedValue,
} from "react-native-reanimated";
import { KeyboardStickyView } from "react-native-keyboard-controller";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

// An empty conversation is not an inverted message row: native and emulated
// list insets position ListEmptyComponent differently. Keep the iOS 300-point
// welcome area above the measured composer on both platforms instead. The
// composer measurement already includes its safe area and bottom spacing.
export function ChatEmptyState({
  agentName,
  composerInset,
  keyboardOffset,
}: {
  agentName: string;
  composerInset: SharedValue<number>;
  keyboardOffset: number;
}) {
  const { colors } = usePreferences();
  const insetStyle = useAnimatedStyle(() => ({
    paddingBottom: composerInset.value,
  }));

  return (
    <KeyboardStickyView
      pointerEvents="none"
      offset={{ closed: 0, opened: keyboardOffset }}
      style={styles.overlay}
    >
      <Reanimated.View style={insetStyle}>
        <View style={styles.empty}>
          <Text
            family="heading"
            style={[styles.title, { color: colors.text }]}
          >
            Start a conversation
          </Text>
          <Text style={[styles.detail, { color: colors.secondaryText }]}>
            Tell {agentName} what you want to accomplish.
          </Text>
        </View>
      </Reanimated.View>
    </KeyboardStickyView>
  );
}

const styles = StyleSheet.create({
  overlay: { position: "absolute", right: 0, bottom: 0, left: 0 },
  empty: {
    minHeight: 300,
    justifyContent: "center",
    alignItems: "center",
    gap: 7,
    padding: 30,
    marginHorizontal: 12,
  },
  title: { fontSize: 21, fontWeight: "500" },
  detail: { fontSize: 14, textAlign: "center" },
});
