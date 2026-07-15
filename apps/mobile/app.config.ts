import type { ExpoConfig } from "expo/config";
import nativeConfigTokens from "./src/theme/native-config.generated.json" with { type: "json" };

const easProjectId =
  process.env.EXPO_PUBLIC_EAS_PROJECT_ID ??
  process.env.EAS_PROJECT_ID ??
  "4efcaf3d-c813-457a-a656-5f27b5975834";

const config: ExpoConfig = {
  name: "Vesta",
  owner: "vesta-cloud",
  slug: "vesta",
  version: "0.1.176",
  scheme: "vesta",
  orientation: "default",
  icon: "../web/app-icon.png",
  userInterfaceStyle: "automatic",
  newArchEnabled: true,
  updates: {
    url: `https://u.expo.dev/${easProjectId}`,
  },
  runtimeVersion: {
    policy: "appVersion",
  },
  ios: {
    bundleIdentifier: "com.vestarun.mobile",
    buildNumber: "1",
    supportsTablet: false,
    associatedDomains: ["applinks:vesta.run"],
    infoPlist: {
      ITSAppUsesNonExemptEncryption: false,
      NSCameraUsageDescription: "Scan a Vesta connection QR code.",
      NSMicrophoneUsageDescription: "Talk to your Vesta agent.",
    },
  },
  android: {
    package: "com.vestarun.mobile",
    adaptiveIcon: {
      foregroundImage: "../web/app-icon.png",
      backgroundColor: nativeConfigTokens.background,
    },
    predictiveBackGestureEnabled: true,
    intentFilters: [
      {
        action: "VIEW",
        autoVerify: true,
        data: [
          {
            scheme: "https",
            host: "vesta.run",
            pathPrefix: "/mobile/",
          },
        ],
        category: ["BROWSABLE", "DEFAULT"],
      },
    ],
  },
  plugins: [
    "expo-router",
    "expo-secure-store",
    [
      "expo-camera",
      {
        cameraPermission: "Scan a Vesta connection QR code.",
        recordAudioAndroid: false,
      },
    ],
    [
      "expo-audio",
      {
        microphonePermission: "Talk to your Vesta agent.",
      },
    ],
    [
      "expo-notifications",
      {
        color: nativeConfigTokens.primary,
        defaultChannel: "vesta",
      },
    ],
    [
      "./plugins/with-blank-launch-screen",
      { backgroundColor: nativeConfigTokens.splashBackground },
    ],
    [
      "expo-splash-screen",
      {
        backgroundColor: nativeConfigTokens.splashBackground,
      },
    ],
  ],
  experiments: {
    typedRoutes: true,
  },
  extra: {
    apiCompat: "0.2",
    ...(easProjectId ? { eas: { projectId: easProjectId } } : {}),
  },
};

export default config;
