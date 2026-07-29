import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { AgentOrb } from "@/components/AgentOrb";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

// The brand lockup: an alive orb over the wordmark and tagline. Pass `orb` to substitute a
// customized one, as the connect screen does for its boot transition and its own pulse.
export function VestaBrand({ orb }: { orb?: ReactNode }) {
  const { colors } = usePreferences();

  return (
    <View style={styles.brand}>
      {orb ?? <AgentOrb status="alive" />}
      <View style={styles.copy}>
        <Text family="wordmark" style={[styles.wordmark, { color: colors.text }]}>
          vesta
        </Text>
        <Text
          adjustsFontSizeToFit
          family="heading"
          minimumFontScale={0.8}
          numberOfLines={1}
          style={[styles.tagline, { color: colors.secondaryText }]}
        >
          with you through life’s journey
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  brand: {
    width: "100%",
    alignItems: "center",
    gap: 9,
  },
  copy: { width: "100%", alignItems: "center", gap: 3.6 },
  wordmark: { fontSize: 43.56, fontWeight: "500", letterSpacing: -1 },
  tagline: {
    width: "100%",
    textAlign: "center",
    fontSize: 18,
    lineHeight: 24,
  },
});
