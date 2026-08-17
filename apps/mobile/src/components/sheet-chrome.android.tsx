import { Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import type { SheetChromeProps } from "@/components/sheet-chrome.types";

// Android form sheets render no native header, grabber, or toolbar item
// (react-native-screens attaches header chrome only to non-sheet screens),
// so the Material 3 sheet chrome renders in content: drag handle, centered
// title, and a labeled close button.
export function SheetChrome({
  title,
  closeLabel,
  grabber = false,
  tintColor,
}: SheetChromeProps) {
  const router = useRouter();
  const { colors } = usePreferences();
  const hasHeaderRow = Boolean(title) || Boolean(closeLabel);

  return (
    <View pointerEvents="box-none" style={styles.chrome}>
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
              family="heading"
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
              android_ripple={{
                color: colors.border,
                borderless: true,
                radius: 20,
              }}
              hitSlop={8}
              style={styles.close}
              onPress={() => router.back()}
            >
              <Ionicons
                name="close"
                size={24}
                color={tintColor ?? colors.secondaryText}
              />
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  chrome: { alignItems: "center", paddingTop: 12 },
  handle: { width: 32, height: 4, borderRadius: 2, opacity: 0.4 },
  headerRow: {
    alignSelf: "stretch",
    minHeight: 48,
    justifyContent: "center",
  },
  title: {
    fontSize: 24,
    fontWeight: "500",
    textAlign: "center",
    paddingHorizontal: 56,
  },
  close: {
    position: "absolute",
    top: 4,
    left: 16,
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
});
