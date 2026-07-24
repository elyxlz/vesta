import { useCallback, useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useSegments } from "expo-router";
import Stack from "expo-router/stack";
import {
  DarkTheme,
  DefaultTheme,
  ThemeProvider,
} from "expo-router/react-navigation";
import { StatusBar } from "expo-status-bar";
import { useFonts } from "expo-font";
import * as SplashScreen from "expo-splash-screen";
import * as WebBrowser from "expo-web-browser";
import { Archivo_400Regular } from "@expo-google-fonts/archivo/400Regular";
import { Archivo_500Medium } from "@expo-google-fonts/archivo/500Medium";
import { Archivo_600SemiBold } from "@expo-google-fonts/archivo/600SemiBold";
import { Archivo_700Bold } from "@expo-google-fonts/archivo/700Bold";
import { Archivo_800ExtraBold } from "@expo-google-fonts/archivo/800ExtraBold";
import { Archivo_900Black } from "@expo-google-fonts/archivo/900Black";
import { JetBrainsMono_400Regular } from "@expo-google-fonts/jetbrains-mono/400Regular";
import { JetBrainsMono_600SemiBold } from "@expo-google-fonts/jetbrains-mono/600SemiBold";
import { JetBrainsMono_700Bold } from "@expo-google-fonts/jetbrains-mono/700Bold";
import { SourceSerif4_400Regular } from "@expo-google-fonts/source-serif-4/400Regular";
import { SourceSerif4_500Medium } from "@expo-google-fonts/source-serif-4/500Medium";
import { SourceSerif4_600SemiBold } from "@expo-google-fonts/source-serif-4/600SemiBold";
import { SourceSerif4_700Bold } from "@expo-google-fonts/source-serif-4/700Bold";
import {
  PreferencesProvider,
  usePreferences,
} from "@/preferences/PreferencesProvider";
import { UserNotifications } from "@/notifications/UserNotifications";
import { PushCoordinator } from "@/notifications/PushCoordinator";
import { WhatsNewAutoOpen } from "@/releases/whats-new-auto-open";
import {
  RosterHoldProvider,
  RosterProvider,
  useRoster,
} from "@/session/RosterProvider";
import { SessionProvider, useSession } from "@/session/SessionProvider";
import { ChatHoldProvider } from "@/chat/ChatHoldProvider";
import { ControllerProvider } from "@/controller/ControllerProvider";
import { BootSplash } from "@/components/BootSplash";
import { GatewayConnectionBanner } from "@/components/GatewayConnectionBanner";
import { Text } from "@/components/ui/Typography";
import {
  BootTransitionProvider,
  type BootDestination,
  type BootTargetFrame,
} from "@/components/BootTransition";
import { fontNames } from "@/theme/typography";

WebBrowser.maybeCompleteAuthSession();
void SplashScreen.preventAutoHideAsync();

function SessionNavigation() {
  const { status, disconnect } = useSession();
  const { agents, agentsReady, reachable } = useRoster();
  const { colors, dark } = usePreferences();
  const segments = useSegments();
  const activeRoute = segments[0];
  const [bootSplashVisible, setBootSplashVisible] = useState(true);
  const [bootPageRevealed, setBootPageRevealed] = useState(false);
  const [bootTargetVisible, setBootTargetVisible] = useState(false);
  const [bootTargets, setBootTargets] = useState<
    Partial<Record<BootDestination, BootTargetFrame>>
  >({});
  const isConnectRoute =
    activeRoute === "connect" ||
    activeRoute === "connect-actions" ||
    activeRoute === "connect-link" ||
    activeRoute === "recent-gateways" ||
    activeRoute === "scan";
  const isHomeRoute = !activeRoute;
  const routeNeedsAgents = isHomeRoute || activeRoute === "agent";
  const navigationTheme = useMemo(() => {
    const base = dark ? DarkTheme : DefaultTheme;
    return {
      ...base,
      dark,
      colors: {
        ...base.colors,
        primary: colors.interactive,
        background: colors.background,
        card: colors.elevated,
        text: colors.text,
        border: colors.border,
        notification: colors.danger,
      },
    };
  }, [colors, dark]);
  const routeMatchesSession =
    (status === "disconnected" && isConnectRoute) ||
    (status === "connected" &&
      !isConnectRoute &&
      (!routeNeedsAgents || agentsReady));
  const destination: BootDestination | null =
    status === "disconnected"
      ? "connect"
      : status === "connected"
        ? activeRoute === "agent"
          ? "agent"
          : "home"
        : null;
  const targetExpected =
    destination === "connect" ||
    destination === "agent" ||
    (destination === "home" && isHomeRoute && agents.length > 0);
  const revealBootPage = useCallback(() => setBootPageRevealed(true), []);
  const revealBootTarget = useCallback(() => setBootTargetVisible(true), []);
  const finishBootSplash = useCallback(() => setBootSplashVisible(false), []);
  const reportBootTarget = useCallback(
    (nextDestination: BootDestination, frame: BootTargetFrame) => {
      setBootTargets((current) => {
        const previous = current[nextDestination];
        if (
          previous?.x === frame.x &&
          previous.y === frame.y &&
          previous.width === frame.width &&
          previous.height === frame.height &&
          previous.status === frame.status &&
          previous.activityState === frame.activityState
        ) {
          return current;
        }
        return { ...current, [nextDestination]: frame };
      });
    },
    [],
  );

  return (
    <BootTransitionProvider
      active={bootSplashVisible}
      onTarget={reportBootTarget}
      pageRevealed={bootPageRevealed}
      targetVisible={bootTargetVisible}
    >
      <View style={[styles.appSurface, { backgroundColor: colors.background }]}>
        <ThemeProvider value={navigationTheme}>
          <StatusBar
            style={
              (bootSplashVisible && !bootPageRevealed) || !dark
                ? "dark"
                : "light"
            }
          />
          <Stack
            screenOptions={{
              contentStyle: { backgroundColor: colors.background },
              headerTransparent: true,
              headerStyle: { backgroundColor: "transparent" },
              headerTintColor: colors.text,
              headerTitleStyle: {
                fontFamily: fontNames.heading.native["500"],
                fontSize: 24,
                fontWeight: "500",
              },
              headerLargeTitleStyle: {
                fontFamily: fontNames.heading.native["500"],
                fontWeight: "500",
              },
              headerShadowVisible: false,
              headerBackButtonDisplayMode: "minimal",
            }}
          >
            <Stack.Protected guard={status !== "connected"}>
              <Stack.Screen
                name="connect"
                options={{
                  headerShown: false,
                  animation: "fade",
                  animationDuration: 500,
                }}
              />
              <Stack.Screen
                name="connect-actions"
                options={{
                  headerShown: false,
                  presentation: "formSheet",
                  sheetAllowedDetents: "fitToContents",
                  sheetGrabberVisible: false,
                  sheetLargestUndimmedDetentIndex: "last",
                  gestureEnabled: false,
                  contentStyle: { backgroundColor: colors.card },
                }}
              />
              <Stack.Screen
                name="connect-link"
                options={{
                  headerShown: false,
                  presentation: "formSheet",
                  sheetAllowedDetents: "fitToContents",
                  sheetGrabberVisible: true,
                  contentStyle: { backgroundColor: colors.card },
                }}
              />
              <Stack.Screen
                name="recent-gateways"
                options={{
                  headerShown: false,
                  presentation: "formSheet",
                  sheetAllowedDetents: "fitToContents",
                  sheetGrabberVisible: true,
                  contentStyle: { backgroundColor: colors.card },
                }}
              />
              <Stack.Screen
                name="scan"
                options={{
                  title: "",
                  headerShown: true,
                  presentation: "formSheet",
                  sheetAllowedDetents: [1],
                  sheetGrabberVisible: false,
                  sheetExpandsWhenScrolledToEdge: false,
                  contentStyle: { backgroundColor: colors.background },
                }}
              />
            </Stack.Protected>
            <Stack.Protected guard={status === "connected"}>
              <Stack.Screen
                name="index"
                options={{ title: "Vesta", headerLargeTitle: true }}
              />
              <Stack.Screen
                name="new-agent"
                options={{
                  headerShown: false,
                  presentation: "formSheet",
                  sheetAllowedDetents: "fitToContents",
                  sheetInitialDetentIndex: 0,
                  sheetGrabberVisible: true,
                  sheetExpandsWhenScrolledToEdge: false,
                }}
              />
              <Stack.Screen
                name="settings"
                options={{
                  title: "Settings",
                  presentation: "formSheet",
                  sheetAllowedDetents: [1],
                  sheetGrabberVisible: false,
                  sheetExpandsWhenScrolledToEdge: false,
                  contentStyle: { backgroundColor: colors.background },
                  headerTitle: () => (
                    <Text
                      family="heading"
                      style={[styles.settingsTitle, { color: colors.text }]}
                    >
                      Settings
                    </Text>
                  ),
                }}
              />
              <Stack.Screen
                name="whats-new"
                options={{
                  title: "What’s new",
                  presentation: "formSheet",
                  sheetAllowedDetents: [1],
                  sheetInitialDetentIndex: 0,
                  sheetGrabberVisible: false,
                  sheetExpandsWhenScrolledToEdge: false,
                  contentStyle: { backgroundColor: colors.background },
                }}
              />
              <Stack.Screen name="debug" options={{ title: "Diagnostics" }} />
              <Stack.Screen
                name="agent/[name]"
                options={{ headerShown: false }}
              />
            </Stack.Protected>
          </Stack>
          <GatewayConnectionBanner
            visible={
              status === "connected" &&
              agentsReady &&
              !reachable &&
              isHomeRoute &&
              !bootSplashVisible
            }
          />
          <WhatsNewAutoOpen enabled={!bootSplashVisible} />
          {bootSplashVisible ? (
            <BootSplash
              ready={routeMatchesSession}
              target={destination ? (bootTargets[destination] ?? null) : null}
              targetExpected={targetExpected}
              onDisconnect={status === "connected" ? disconnect : undefined}
              onHandoff={revealBootTarget}
              onReveal={revealBootPage}
              onFinish={finishBootSplash}
            />
          ) : null}
        </ThemeProvider>
      </View>
    </BootTransitionProvider>
  );
}

const styles = StyleSheet.create({
  appSurface: { flex: 1 },
  settingsTitle: {
    fontSize: 24,
    lineHeight: 30,
    fontWeight: "500",
    letterSpacing: -0.7,
  },
});

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({
    Archivo_400Regular,
    Archivo_500Medium,
    Archivo_600SemiBold,
    Archivo_700Bold,
    Archivo_800ExtraBold,
    Archivo_900Black,
    JetBrainsMono_400Regular,
    JetBrainsMono_600SemiBold,
    JetBrainsMono_700Bold,
    SourceSerif4_400Regular,
    SourceSerif4_500Medium,
    SourceSerif4_600SemiBold,
    SourceSerif4_700Bold,
  });
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 15_000, retry: 1 },
          mutations: { retry: 0 },
        },
      }),
  );
  if (!fontsLoaded && !fontError) return null;
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <KeyboardProvider>
        <QueryClientProvider client={queryClient}>
          <PreferencesProvider>
            <SessionProvider>
              <RosterHoldProvider>
                <ChatHoldProvider>
                  <ControllerProvider>
                    <RosterProvider>
                      <UserNotifications />
                      <PushCoordinator />
                      <SessionNavigation />
                    </RosterProvider>
                  </ControllerProvider>
                </ChatHoldProvider>
              </RosterHoldProvider>
            </SessionProvider>
          </PreferencesProvider>
        </QueryClientProvider>
      </KeyboardProvider>
    </GestureHandlerRootView>
  );
}
