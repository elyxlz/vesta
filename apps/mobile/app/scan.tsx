import { useEffect, useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { CameraView, useCameraPermissions } from "expo-camera";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Button } from "@/components/ui/Button";
import { LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import {
  ThemeOverrideProvider,
  usePreferences,
} from "@/preferences/PreferencesProvider";

export default function ScanScreen() {
  return (
    <ThemeOverrideProvider theme="light">
      <ScanContent />
    </ThemeOverrideProvider>
  );
}

function ScanContent() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = usePreferences();
  const [permission, requestPermission] = useCameraPermissions();
  const [scanned, setScanned] = useState(false);

  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain) {
      void requestPermission();
    }
  }, [permission, requestPermission]);

  const backButton = (
    <ScannerBackButton
      top={Math.max(insets.top, 12) + 8}
      onPress={() => router.back()}
    />
  );

  if (!permission) {
    return (
      <View style={[styles.screen, { backgroundColor: colors.background }]}>
        <LoadingState label="Checking camera access…" />
        {backButton}
      </View>
    );
  }
  if (!permission.granted) {
    return (
      <View style={[styles.state, { backgroundColor: colors.background }]}>
        <Text family="heading" style={[styles.title, { color: colors.text }]}>
          Camera access is needed
        </Text>
        <Text style={[styles.detail, { color: colors.secondaryText }]}>
          Vesta uses the camera only to scan your connection QR code.
        </Text>
        {permission.canAskAgain ? (
          <Button onPress={() => void requestPermission()}>Allow camera</Button>
        ) : null}
        {backButton}
      </View>
    );
  }

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <CameraView
        style={StyleSheet.absoluteFill}
        barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
        onBarcodeScanned={
          scanned
            ? undefined
            : ({ data }) => {
                setScanned(true);
                router.dismissTo({
                  pathname: "/connect-link",
                  params: {
                    link: data,
                    autoConnect: "true",
                    scanId: String(Date.now()),
                  },
                });
              }
        }
      />
      <View style={styles.overlay} pointerEvents="none">
        <View style={styles.finder} />
        <Text family="heading" style={styles.hint}>
          Center the gateway QR code
        </Text>
      </View>
      {backButton}
    </View>
  );
}

function ScannerBackButton({
  top,
  onPress,
}: {
  top: number;
  onPress: () => void;
}) {
  const button = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Go back"
      hitSlop={8}
      onPress={onPress}
      style={({ pressed }) => [
        styles.backButtonContent,
        { opacity: pressed ? 0.72 : 1 },
      ]}
    >
      <Ionicons name="chevron-back" size={26} color="white" />
    </Pressable>
  );

  if (isGlassEffectAPIAvailable()) {
    return (
      <GlassView
        glassEffectStyle="regular"
        colorScheme="dark"
        isInteractive
        style={[styles.backButton, { top }]}
      >
        {button}
      </GlassView>
    );
  }

  return (
    <View style={[styles.backButton, styles.backButtonFallback, { top }]}>
      {button}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  overlay: { flex: 1, justifyContent: "center", alignItems: "center", gap: 24 },
  finder: {
    width: 248,
    height: 248,
    borderRadius: 30,
    borderWidth: 3,
    borderColor: "white",
  },
  hint: {
    color: "white",
    fontSize: 16,
    fontWeight: "700",
    textShadowColor: "black",
    textShadowRadius: 6,
  },
  backButton: {
    position: "absolute",
    left: 16,
    zIndex: 2,
    width: 46,
    height: 46,
    borderRadius: 23,
    overflow: "hidden",
  },
  backButtonContent: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  backButtonFallback: {
    backgroundColor: "rgba(10, 10, 10, 0.48)",
  },
  state: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: 14,
    padding: 28,
  },
  title: { fontSize: 22, fontWeight: "500", textAlign: "center" },
  detail: { fontSize: 15, lineHeight: 21, textAlign: "center" },
});
