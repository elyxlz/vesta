import type { ReactNode } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { spacing } from "@/theme/layout";

const IS_IOS = process.env.EXPO_OS === "ios";

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
  const insets = useSafeAreaInsets();
  const backgroundColor = transparent ? "transparent" : colors.background;
  if (!scroll) {
    return (
      <View style={[styles.screen, { backgroundColor }, contentStyle]}>
        {children}
      </View>
    );
  }
  // iOS adds the bottom safe-area inset through automatic content-inset
  // adjustment; Android has no such mechanism, so fold it into the padding.
  const flattened = StyleSheet.flatten([styles.content, contentStyle]);
  const androidBottomInset = IS_IOS
    ? null
    : {
        paddingBottom:
          (typeof flattened.paddingBottom === "number"
            ? flattened.paddingBottom
            : 0) + insets.bottom,
      };
  return (
    <ScrollView
      style={[styles.screen, { backgroundColor }]}
      contentContainerStyle={[styles.content, contentStyle, androidBottomInset]}
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
