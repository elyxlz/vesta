import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Linking, StyleSheet, View } from "react-native";
import type { WebViewMessageEvent, ShouldStartLoadRequest } from "react-native-webview/lib/WebViewTypes";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { serviceKeyPathUrl } from "@vesta/core";
import { useServiceKey } from "@vesta/core/react";
import { useAgent } from "@/agent/AgentProvider";
import { DashboardWebView, type DashboardWebViewHandle } from "@/components/DashboardWebView";
import { EmptyState } from "@/components/ui/States";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { navHeaderHeight } from "@/theme/layout";

interface DashboardMessage {
  type?: string;
  url?: string;
}

export default function DashboardPage() {
  const webView = useRef<DashboardWebViewHandle>(null);
  const insets = useSafeAreaInsets();
  const { name, agent } = useAgent();
  const { connection, api } = useSession();
  const { colors, dark } = usePreferences();
  const [loadError, setLoadError] = useState<{
    url: string;
    message: string;
  } | null>(null);
  const dashboard = agent?.services.dashboard;
  const hasDashboard = !!dashboard;

  // The dashboard is a private service, so the WebView authenticates with a minted service key
  // carried in the path: the document sends no header, and its relative asset requests inherit
  // neither a header nor a query string.
  const { key: dashboardKey, error: keyError } = useServiceKey(
    api.serviceKeys,
    name,
    "dashboard",
    hasDashboard,
  );

  const dashboardUrl =
    dashboard && connection && dashboardKey
      ? serviceKeyPathUrl(connection.url, name, "dashboard", dashboardKey)
      : null;

  // Both errors are derived rather than latched into state. The hook retries a failed mint and
  // clears its own error, so a mirrored copy would outlive the failure; a load failure is scoped
  // to the URL that produced it, so a fresh key replacing a revoked one gets its own try.
  const shownError =
    (loadError !== null && loadError.url === dashboardUrl
      ? loadError.message
      : "") || (keyError == null ? "" : String(keyError));

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
    webView.current?.sendBridgeMessages(bridgeMessages);
  }, [bridgeMessages]);

  // Deliver bridge state to an already-loaded page, not only on first load.
  useEffect(() => {
    sendContext();
  }, [sendContext]);

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
          paddingTop: insets.top + navHeaderHeight,
          paddingBottom: insets.bottom,
        },
      ]}
    >
      {!hasDashboard ? (
        <EmptyState
          title="Your dashboard"
          detail={`Ask ${name} to set up the dashboard and add some widgets.`}
        />
      ) : shownError ? (
        <EmptyState title="Dashboard unavailable" detail={shownError} />
      ) : (
        <View
          style={[
            styles.webShell,
            { backgroundColor: colors.card, borderColor: colors.border },
          ]}
        >
          {dashboardUrl && (
            <DashboardWebView
              key={`${name}-${dashboard?.rev ?? 0}`}
              ref={webView}
              bridgeMessages={bridgeMessages}
              dark={dark}
              source={{ uri: dashboardUrl }}
              style={styles.webView}
              containerStyle={styles.webView}
              originWhitelist={["https://*", "http://*"]}
              onLoad={sendContext}
              onMessage={onMessage}
              onShouldStartLoadWithRequest={allowNavigation}
              onError={(event) =>
                setLoadError({
                  url: dashboardUrl,
                  message: event.nativeEvent.description,
                })
              }
            />
          )}
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
