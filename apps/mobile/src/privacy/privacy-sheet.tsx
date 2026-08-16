import { StyleSheet, View } from "react-native";
import { LoadingSpinner } from "@/components/loading-spinner";
import Animated, { FadeIn } from "react-native-reanimated";
import { AuthPrimaryButton } from "@/components/auth-primary-button";
import { AuthSheet } from "@/components/auth-sheet";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { usePrivacy } from "./privacy-provider";

const CONTENT_TRANSITION_MS = 180;

export function PrivacySheet() {
  const privacy = usePrivacy();
  const { colors } = usePreferences();
  const unlockLabel =
    privacy.authenticationName === "device authentication"
      ? "Unlock Vesta"
      : `Unlock with ${privacy.authenticationName}`;
  const initializationFailed = privacy.initializationError !== null;
  const unlockFailed =
    privacy.hydrated && !initializationFailed && privacy.unlockError !== null;
  const stateKey = initializationFailed
    ? "initialization-failed"
    : unlockFailed
      ? "unlock-failed"
      : privacy.hydrated
        ? "locked"
        : "opening";
  const title = initializationFailed
    ? "Privacy unavailable"
    : unlockFailed
      ? "Unlock failed"
      : privacy.hydrated
        ? "Vesta is locked"
        : "Opening Vesta";
  const detail = initializationFailed
    ? privacy.initializationError
    : unlockFailed
      ? privacy.unlockError
      : privacy.hydrated
        ? "Authenticate to return to your agents."
        : "Checking your privacy settings.";
  const errorState = initializationFailed || unlockFailed;

  return (
    <AuthSheet gap={20}>
      <Animated.View
        key={stateKey}
        entering={FadeIn.duration(CONTENT_TRANSITION_MS)}
        accessibilityLiveRegion={errorState ? "assertive" : "polite"}
        style={styles.copy}
      >
        <Text
          accessibilityRole="header"
          family="heading"
          style={[styles.title, { color: colors.text }]}
        >
          {title}
        </Text>
        <Text
          accessibilityRole={errorState ? "alert" : undefined}
          selectable={errorState}
          style={[styles.detail, { color: colors.secondaryText }]}
        >
          {detail}
        </Text>
      </Animated.View>
      {initializationFailed ? (
        <AuthPrimaryButton onPress={privacy.retryInitialization}>
          Try again
        </AuthPrimaryButton>
      ) : privacy.hydrated ? (
        <AuthPrimaryButton
          loading={privacy.authenticating}
          disabled={privacy.authenticating}
          onPress={() => void privacy.unlock()}
        >
          {unlockLabel}
        </AuthPrimaryButton>
      ) : (
        <View
          accessibilityLabel="Checking privacy settings"
          accessibilityRole="progressbar"
          style={styles.progress}
        >
          <LoadingSpinner color={colors.interactive} />
        </View>
      )}
    </AuthSheet>
  );
}

const styles = StyleSheet.create({
  copy: { alignItems: "center", gap: 7 },
  title: {
    fontSize: 25,
    lineHeight: 31,
    fontWeight: "600",
    letterSpacing: -0.5,
    textAlign: "center",
  },
  detail: { fontSize: 15, lineHeight: 21, textAlign: "center" },
  progress: { minHeight: 50, alignItems: "center", justifyContent: "center" },
});
