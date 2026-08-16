import { useEffect, useState } from "react";
import { AppState, Linking, StyleSheet, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { Stack, useRouter } from "expo-router";
import { AuthPrimaryButton } from "@/components/auth-primary-button";
import { LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { usePrivacyBlocked } from "@/privacy/use-privacy-blocked";

export default function ScanScreen() {
  return <ScanContent />;
}

function ScanContent() {
  const router = useRouter();
  const { colors, dark } = usePreferences();
  const privacyBlocked = usePrivacyBlocked();
  const [permission, requestPermission, getPermission] = useCameraPermissions();
  const [scanned, setScanned] = useState(false);

  useEffect(() => {
    if (
      !privacyBlocked &&
      permission &&
      !permission.granted &&
      permission.canAskAgain
    ) {
      void requestPermission();
    }
  }, [permission, privacyBlocked, requestPermission]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void getPermission();
    });
    return () => subscription.remove();
  }, [getPermission]);

  const headerTintColor = permission?.granted ? "white" : colors.text;
  const header = (
    <>
      <Stack.Screen
        options={{
          headerTintColor,
          statusBarStyle: permission?.granted || dark ? "light" : "dark",
        }}
      />
      <NativeSheetCloseButton
        accessibilityLabel="Close scanner"
        tintColor={headerTintColor}
      />
      <View pointerEvents="box-none" style={styles.androidChrome}>
        <SheetChrome closeLabel="Close scanner" tintColor={headerTintColor} />
      </View>
    </>
  );

  if (privacyBlocked) return null;

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
            <AuthPrimaryButton onPress={() => void requestPermission()}>
              Allow camera
            </AuthPrimaryButton>
          ) : (
            <AuthPrimaryButton
              icon="settings-outline"
              onPress={() => void Linking.openSettings()}
            >
              Open Settings
            </AuthPrimaryButton>
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
        </View>
      </View>
      {header}
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  androidChrome: { position: "absolute", top: 0, left: 0, right: 0 },
  overlay: { flex: 1, justifyContent: "center", alignItems: "center" },
  finder: {
    width: 248,
    height: 248,
    borderRadius: 30,
    borderWidth: 3,
    borderColor: "white",
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
