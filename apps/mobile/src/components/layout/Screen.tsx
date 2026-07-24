import type { ReactNode } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { spacing } from "@/theme/layout";

interface ScreenProps {
  children: ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  contentStyle?: StyleProp<ViewStyle>;
  transparent?: boolean;
}

export function Screen({
  children,
  scroll = true,
  refreshing = false,
  onRefresh,
  contentStyle,
  transparent = false,
}: ScreenProps) {
  const { colors } = usePreferences();
  const backgroundColor = transparent ? "transparent" : colors.background;
  if (!scroll) {
    return (
      <View style={[styles.screen, { backgroundColor }, contentStyle]}>
        {children}
      </View>
    );
  }
  return (
    <ScrollView
      style={[styles.screen, { backgroundColor }]}
      contentContainerStyle={[styles.content, contentStyle]}
      contentInsetAdjustmentBehavior="automatic"
      keyboardDismissMode="interactive"
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefresh ? (
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.accent}
          />
        ) : undefined
      }
    >
      {children}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: {
    paddingHorizontal: spacing.page,
    paddingTop: 12,
    paddingBottom: 40,
    gap: 16,
  },
});
