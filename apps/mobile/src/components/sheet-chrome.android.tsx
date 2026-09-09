import { Pressable, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { headerTitleStyle } from "@/theme/sheets";
import type { SheetChromeProps } from "@/components/sheet-chrome.types";

// Android form sheets render no native header, grabber, or toolbar item
// (react-native-screens attaches header chrome only to non-sheet screens),
// so their in-content header mirrors the native iOS title and circular controls.
export function SheetChrome({
  title,
  closeLabel,
  grabber = false,
  tintColor,
  action,
}: SheetChromeProps) {
  const router = useRouter();
  const { colors } = usePreferences();
  const hasHeaderRow = Boolean(title) || Boolean(closeLabel) || Boolean(action);
  const buttonSurface = { backgroundColor: colors.elevated };

  return (
    <View
      pointerEvents="box-none"
      style={[styles.chrome, hasHeaderRow ? styles.headerSpacing : null]}
    >
      {grabber ? (
        <View
          style={[styles.handle, { backgroundColor: colors.secondaryText }]}
        />
      ) : null}
      {hasHeaderRow ? (
        <View pointerEvents="box-none" style={styles.headerRow}>
          {title ? (
            <Text
              accessibilityRole="header"
              numberOfLines={1}
              style={[styles.title, { color: tintColor ?? colors.text }]}
            >
              {title}
            </Text>
          ) : null}
          {closeLabel ? (
            <Pressable
              accessibilityLabel={closeLabel}
              accessibilityRole="button"
              android_ripple={{ color: colors.border, radius: 22 }}
              hitSlop={8}
              style={[styles.button, styles.close, buttonSurface]}
              onPress={() => router.back()}
            >
              <Ionicons
                name="close-outline"
                size={32}
                color={tintColor ?? colors.text}
              />
            </Pressable>
          ) : null}
          {action ? (
            <Pressable
              accessibilityLabel={action.accessibilityLabel}
              accessibilityRole="button"
              android_ripple={{ color: colors.border, radius: 22 }}
              hitSlop={8}
              style={[styles.button, styles.action, buttonSurface]}
              onPress={action.onPress}
            >
              {action.icon}
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  chrome: { alignItems: "center", paddingTop: 12 },
  headerSpacing: { paddingBottom: 8 },
  handle: { width: 32, height: 4, borderRadius: 2, opacity: 0.4 },
  headerRow: {
    alignSelf: "stretch",
    minHeight: 48,
    justifyContent: "center",
  },
  title: {
    ...headerTitleStyle,
    textAlign: "center",
    paddingHorizontal: 64,
  },
  button: {
    position: "absolute",
    top: 2,
    width: 44,
    height: 44,
    borderRadius: 22,
    borderCurve: "continuous",
    alignItems: "center",
    justifyContent: "center",
  },
  close: { left: 16 },
  action: { right: 16 },
});
