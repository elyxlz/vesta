import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { blocksProtectedContent } from "./model";
import { usePrivacy } from "./privacy-provider";

export function PrivacyGate({ children }: { children: ReactNode }) {
  const { colors } = usePreferences();
  const privacy = usePrivacy();
  const blocked = blocksProtectedContent(privacy.hydrated, privacy.locked);
  const unlockLabel =
    privacy.authenticationName === "device authentication"
      ? "Unlock Vesta"
      : `Unlock with ${privacy.authenticationName}`;

  return (
    <View style={styles.root}>
      <View
        accessibilityElementsHidden={blocked}
        importantForAccessibility={blocked ? "no-hide-descendants" : "auto"}
        style={styles.content}
      >
        {children}
      </View>
      {blocked ? (
        <View
          accessibilityViewIsModal
          importantForAccessibility="yes"
          style={[styles.overlay, { backgroundColor: colors.background }]}
        >
          <View
            style={[
              styles.icon,
              { backgroundColor: colors.card, borderColor: colors.border },
            ]}
          >
            <Ionicons
              name="lock-closed-outline"
              size={30}
              color={colors.text}
            />
          </View>
          <View style={styles.copy}>
            <Text
              accessibilityRole="header"
              family="heading"
              style={[styles.title, { color: colors.text }]}
            >
              {privacy.hydrated ? "Vesta is locked" : "Opening Vesta"}
            </Text>
            <Text style={[styles.detail, { color: colors.secondaryText }]}>
              {privacy.hydrated
                ? "Authenticate to return to your agents."
                : "Checking your privacy settings."}
            </Text>
            {privacy.hydrated && privacy.unlockError ? (
              <Text
                accessibilityRole="alert"
                selectable
                style={[styles.error, { color: colors.danger }]}
              >
                {privacy.unlockError}
              </Text>
            ) : null}
          </View>
          {privacy.hydrated ? (
            <Button
              loading={privacy.authenticating}
              disabled={privacy.authenticating}
              onPress={() => void privacy.unlock()}
            >
              {unlockLabel}
            </Button>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { flex: 1 },
  overlay: {
    position: "absolute",
    inset: 0,
    zIndex: 1000,
    paddingHorizontal: 28,
    alignItems: "stretch",
    justifyContent: "center",
    gap: 24,
  },
  icon: {
    alignSelf: "center",
    width: 68,
    height: 68,
    borderRadius: 24,
    borderCurve: "continuous",
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: "center",
    justifyContent: "center",
  },
  copy: { alignItems: "center", gap: 7 },
  title: {
    fontSize: 25,
    lineHeight: 31,
    fontWeight: "600",
    letterSpacing: -0.5,
  },
  detail: { fontSize: 15, lineHeight: 21, textAlign: "center" },
  error: { fontSize: 14, lineHeight: 20, textAlign: "center" },
});
