import type { ExpoConfig } from "expo/config";
import nativeConfigTokens from "./src/theme/native-config.generated.json" with { type: "json" };

const easProjectId =
  process.env.EXPO_PUBLIC_EAS_PROJECT_ID ??
  process.env.EAS_PROJECT_ID ??
  "4efcaf3d-c813-457a-a656-5f27b5975834";
const appVariant =
  process.env.VESTA_APP_VARIANT === "development"
    ? "development"
    : "production";
const isDevelopment = appVariant === "development";
const localIosNoPush = process.env.VESTA_LOCAL_IOS_NO_PUSH === "1";
const bundleIdentifier =
  process.env.VESTA_APP_BUNDLE_ID ??
  (isDevelopment ? "com.vesta.mobile.dev" : "com.vesta.mobile");
const appIcon = isDevelopment
  ? "./assets/app-icon-dev.png"
  : "../web/app-icon.png";
const notificationPlugins = localIosNoPush
  ? []
  : ([
      [
        "expo-notifications",
        {
          color: nativeConfigTokens.primary,
          defaultChannel: "vesta",
        },
      ],
    ] satisfies NonNullable<ExpoConfig["plugins"]>);

const config: ExpoConfig = {
  name: isDevelopment ? "Vesta Dev" : "Vesta",
  owner: "vesta-cloud",
  slug: "vesta",
  version: "0.1.177",
  scheme: isDevelopment ? "vesta-dev" : "vesta",
  orientation: "portrait",
  icon: appIcon,
  userInterfaceStyle: "automatic",
  newArchEnabled: true,
  updates: {
    url: `https://u.expo.dev/${easProjectId}`,
  },
  runtimeVersion: {
    policy: "appVersion",
  },
  ios: {
    bundleIdentifier,
    buildNumber: "1",
    supportsTablet: false,
    ...(localIosNoPush
      ? { appleTeamId: "H78XNVF428" }
      : { associatedDomains: ["applinks:vesta.run"] }),
    infoPlist: {
      ITSAppUsesNonExemptEncryption: false,
      NSCameraUsageDescription: "Scan a Vesta connection QR code.",
      NSMicrophoneUsageDescription: "Talk to your Vesta agent.",
    },
  },
  android: {
    package: bundleIdentifier,
    adaptiveIcon: {
      foregroundImage: appIcon,
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
    "expo-status-bar",
    "expo-web-browser",
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
    ...notificationPlugins,
    [
      "./plugins/with-blank-launch-screen",
      { backgroundColor: nativeConfigTokens.splashBackground },
    ],
    [
      "expo-splash-screen",
      {
        backgroundColor: nativeConfigTokens.splashBackground,
        android: {
          // Expo's Android theme always references a splash drawable. Keep the
          // native launch screen visually blank while still generating the
          // resource required by Android's linker.
          drawable: { icon: "./assets/blank-splash.xml" },
        },
      },
    ],
    ...(localIosNoPush ? ["./plugins/with-local-ios-no-push"] : []),
  ],
  experiments: {
    typedRoutes: true,
    reactCompiler: true,
  },
  extra: {
    apiCompat: "0.2",
    appVariant,
    pushNotificationsEnabled: !localIosNoPush,
    ...(easProjectId ? { eas: { projectId: easProjectId } } : {}),
  },
};

export default config;
