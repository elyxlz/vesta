import type { ProviderIdentity } from "@vesta/core";
import { StyleSheet, View } from "react-native";
import { ProviderLogo } from "@/components/ProviderLogo";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

export function ProviderPill({ identity }: { identity: ProviderIdentity }) {
  const { colors } = usePreferences();
  return (
    <View
      style={[
        styles.pill,
        { backgroundColor: colors.elevated, borderColor: colors.border },
      ]}
    >
      <ProviderLogo kind={identity.kind} size={14} />
      <Text
        numberOfLines={1}
        style={[styles.label, { color: colors.secondaryText }]}
      >
        {identity.modelName ?? identity.providerName}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    alignItems: "center",
    alignSelf: "flex-start",
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: "row",
    gap: 6,
    maxWidth: "100%",
    paddingHorizontal: 9,
    paddingVertical: 5,
  },
  label: { flexShrink: 1, fontSize: 12 },
});
