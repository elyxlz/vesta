import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { AgentOrb } from "@/components/AgentOrb";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

// The brand lockup: an alive orb over the wordmark. Pass `orb` to substitute a
// customized one, as the connect screen does for its boot transition and its own pulse.
export const BRAND_ORB_SIZE = 64;

export function VestaBrand({ orb }: { orb?: ReactNode }) {
  const { colors } = usePreferences();

  return (
    <View style={styles.brand}>
      {orb ?? <AgentOrb status="alive" size={BRAND_ORB_SIZE} />}
      <Text family="wordmark" style={[styles.wordmark, { color: colors.text }]}>
        vesta
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  brand: {
    width: "100%",
    alignItems: "center",
    gap: 9,
  },
  wordmark: { fontSize: 48, fontWeight: "500", letterSpacing: -1 },
});
