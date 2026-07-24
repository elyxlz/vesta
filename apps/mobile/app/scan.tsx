import { useEffect, useState } from "react";
import { AppState, Linking, StyleSheet, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { Stack, useRouter } from "expo-router";
import { Button } from "@/components/ui/Button";
import { LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_IOS = process.env.EXPO_OS === "ios";

export default function ScanScreen() {
  return <ScanContent />;
}

function ScanContent() {
  const router = useRouter();
  const { colors } = usePreferences();
  const [permission, requestPermission, getPermission] =
    useCameraPermissions();
  const [scanned, setScanned] = useState(false);

  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain) {
      void requestPermission();
    }
  }, [permission, requestPermission]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void getPermission();
    });
    return () => subscription.remove();
  }, [getPermission]);

  const headerTintColor = permission?.granted ? "white" : colors.text;
  const header = (
    <>
      <Stack.Screen options={{ headerTintColor }} />
      <Stack.Toolbar placement="left">
        <Stack.Toolbar.Button
          accessibilityLabel="Close scanner"
          icon={IS_IOS ? "xmark" : undefined}
          separateBackground
          tintColor={headerTintColor}
          onPress={() => router.back()}
        >
          {IS_IOS ? undefined : "Close"}
        </Stack.Toolbar.Button>
      </Stack.Toolbar>
    </>
  );

  if (!permission) {
    return (
      <>
        <View style={[styles.screen, { backgroundColor: colors.background }]}>
          <LoadingState label="Checking camera access…" />
        </View>
        {header}
      </>
    );
  }
  if (!permission.granted) {
    return (
      <>
        <View style={[styles.state, { backgroundColor: colors.background }]}>
          <Text family="heading" style={[styles.title, { color: colors.text }]}>
            Camera access is needed
          </Text>
          <Text style={[styles.detail, { color: colors.secondaryText }]}>
            Vesta uses the camera only to scan your connection QR code.
          </Text>
          {permission.canAskAgain ? (
            <Button pill onPress={() => void requestPermission()}>
              Allow camera
            </Button>
          ) : (
            <Button
              pill
              icon="settings-outline"
              onPress={() => void Linking.openSettings()}
            >
              Open Settings
            </Button>
          )}
        </View>
        {header}
      </>
    );
  }

  return (
    <>
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
          <Text style={styles.hint}>Center the gateway QR code</Text>
        </View>
      </View>
      {header}
    </>
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
    fontWeight: "500",
    textShadowColor: "black",
    textShadowRadius: 6,
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
