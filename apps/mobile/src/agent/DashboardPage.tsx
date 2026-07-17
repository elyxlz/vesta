import { useCallback, useMemo, useRef, useState } from "react";
import { Linking, Platform, StyleSheet, View } from "react-native";
import type { WebViewMessageEvent, ShouldStartLoadRequest } from "react-native-webview/lib/WebViewTypes";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAgent } from "@/agent/AgentProvider";
import { DashboardWebView, type DashboardWebViewHandle } from "@/components/DashboardWebView";
import { EmptyState } from "@/components/ui/States";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

interface DashboardMessage {
  type?: string;
  url?: string;
}

export default function DashboardPage() {
  const webView = useRef<DashboardWebViewHandle>(null);
  const insets = useSafeAreaInsets();
  const { name, agent } = useAgent();
  const { connection } = useSession();
  const { colors, dark } = usePreferences();
  const [error, setError] = useState("");
  const dashboard = agent?.services.dashboard;
  const dashboardUrl =
    dashboard && connection
      ? `${connection.url}/agents/${encodeURIComponent(name)}/dashboard/`
      : null;

  const bridgeMessages = useMemo<readonly Record<string, unknown>[]>(
    () =>
      connection
        ? [
            { type: "vesta-theme", dark },
            { type: "vesta-layout", fullscreen: true },
            {
              type: "vesta-platform",
              isDesktopApp: false,
              platform: "mobile",
              isDesktop: false,
              isMobile: true,
              vibrancy: true,
            },
            {
              type: "vesta-auth",
              token: connection.accessToken,
              baseUrl: `${connection.url}/agents/${encodeURIComponent(name)}`,
              agentName: name,
            },
          ]
        : [],
    [connection, dark, name],
  );

  const sendContext = useCallback(() => {
    for (const message of bridgeMessages) {
      webView.current?.postMessage(JSON.stringify(message));
    }
  }, [bridgeMessages]);

  const onMessage = (event: WebViewMessageEvent) => {
    let message: DashboardMessage;
    try {
      message = JSON.parse(event.nativeEvent.data);
    } catch {
      return;
    }
    if (message.type?.endsWith("-request")) sendContext();
    if (
      message.type === "vesta-open-url" &&
      message.url &&
      /^(https?:|mailto:|tel:)/i.test(message.url)
    ) {
      void Linking.openURL(message.url);
    }
  };

  const allowNavigation = (request: ShouldStartLoadRequest): boolean => {
    if (!dashboardUrl) return false;
    if (request.url.startsWith(dashboardUrl)) return true;
    if (/^(about:blank|data:)/i.test(request.url)) return true;
    if (/^(https?:|mailto:|tel:)/i.test(request.url)) {
      void Linking.openURL(request.url);
    }
    return false;
  };

  return (
    <View
      style={[
        styles.screen,
        {
          paddingTop: insets.top + (Platform.OS === "ios" ? 44 : 56),
          paddingBottom: insets.bottom,
        },
      ]}
    >
      {!dashboardUrl ? (
        <EmptyState
          title="Your dashboard"
          detail={`Ask ${name} to set up the dashboard and add some widgets.`}
        />
      ) : error ? (
        <EmptyState title="Dashboard unavailable" detail={error} />
      ) : (
        <View
          style={[
            styles.webShell,
            { backgroundColor: colors.card, borderColor: colors.border },
          ]}
        >
          <DashboardWebView
            key={`${name}-${dashboard?.rev ?? 0}`}
            ref={webView}
            bridgeMessages={bridgeMessages}
            dark={dark}
            source={{
              uri: dashboardUrl,
              headers: connection
                ? { Authorization: `Bearer ${connection.accessToken}` }
                : undefined,
            }}
            style={styles.webView}
            containerStyle={styles.webView}
            originWhitelist={["https://*", "http://*"]}
            onLoad={sendContext}
            onMessage={onMessage}
            onShouldStartLoadWithRequest={allowNavigation}
            onError={(event) => setError(event.nativeEvent.description)}
          />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  webShell: {
    flex: 1,
    marginHorizontal: 16,
    marginTop: 16,
    borderRadius: 22,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: "hidden",
  },
  webView: { flex: 1, backgroundColor: "transparent" },
});
