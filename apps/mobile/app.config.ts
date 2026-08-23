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
  version: "0.2.9",
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
      // Keeps a hands-free voice session (mic + speech) alive with the screen
      // locked, for use over a car or headset Bluetooth connection.
      UIBackgroundModes: ["audio"],
    },
  },
  android: {
    package: bundleIdentifier,
    adaptiveIcon: {
      foregroundImage: appIcon,
      backgroundColor: nativeConfigTokens.background,
    },
    edgeToEdgeEnabled: true,
    predictiveBackGestureEnabled: true,
    permissions: [
      "android.permission.CAMERA",
      "android.permission.RECORD_AUDIO",
      "android.permission.POST_NOTIFICATIONS",
    ],
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
      "expo-local-authentication",
      {
        faceIDPermission: "Use Face ID to unlock Vesta.",
      },
    ],
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
    "expo-localization",
    [
      "expo-location",
      {
        locationWhenInUsePermission:
          "Let Vesta know where you are, to help you wherever you go.",
        locationAlwaysAndWhenInUsePermission:
          "Let Vesta know where you are, even while the app is closed, to help you wherever you go.",
        locationAlwaysPermission:
          "Let Vesta know where you are while the app is closed, to help you wherever you go.",
        // The closed-app poll reads a fresh fix, which needs the always-on grant on both platforms
        // and, on iOS, the location background mode as well; the processing mode alone cannot get one.
        isIosBackgroundLocationEnabled: true,
        isAndroidBackgroundLocationEnabled: true,
      },
    ],
    "expo-background-task",
    [
      "expo-splash-screen",
      {
        backgroundColor: nativeConfigTokens.splashBackground,
        dark: {
          backgroundColor: nativeConfigTokens.splashBackgroundDark,
        },
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
    // Vesta Cloud is not open to the public yet: production builds offer
    // self-hosted connection only, so App Review never meets a sign-in it
    // cannot complete. Flip to true when cloud sign-up opens.
    cloudSignInEnabled: isDevelopment,
    pushNotificationsEnabled: !localIosNoPush,
    ...(easProjectId ? { eas: { projectId: easProjectId } } : {}),
  },
};

export default config;
