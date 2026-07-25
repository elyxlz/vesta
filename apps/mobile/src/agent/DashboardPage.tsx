import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Linking, Platform, StyleSheet, View } from "react-native";
import type { WebViewMessageEvent, ShouldStartLoadRequest } from "react-native-webview/lib/WebViewTypes";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAgent } from "@/agent/AgentProvider";
import { mintDashboardToken } from "@/api/endpoints";
import { DashboardWebView, type DashboardWebViewHandle } from "@/components/DashboardWebView";
import { EmptyState } from "@/components/ui/States";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

interface DashboardMessage {
  type?: string;
  url?: string;
}

// The WebView holds a short-lived capability scoped to this agent's service routes, never
// the gateway token; re-mint well before expiry so an open dashboard keeps working.
const DASHBOARD_TOKEN_REMINT_FRACTION = 0.8;
const DASHBOARD_TOKEN_RETRY_MS = 5000;

export default function DashboardPage() {
  const webView = useRef<DashboardWebViewHandle>(null);
  const insets = useSafeAreaInsets();
  const { name, agent } = useAgent();
  const { connection, api } = useSession();
  const { colors, dark } = usePreferences();
  const [error, setError] = useState("");
  const dashboard = agent?.services.dashboard;
  const hasDashboard = !!dashboard;
  const dashboardUrl =
    dashboard && connection
      ? `${connection.url}/agents/${encodeURIComponent(name)}/dashboard/`
      : null;

  // Derived, not reset: a token minted for another agent is simply never used.
  const [minted, setMinted] = useState<{ agent: string; token: string } | null>(
    null,
  );
  const dashboardToken = minted?.agent === name ? minted.token : null;
  useEffect(() => {
    if (!hasDashboard) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const mint = async () => {
      try {
        const { token, expires_in } = await mintDashboardToken(api, name);
        if (cancelled) return;
        setMinted({ agent: name, token });
        timer = setTimeout(
          () => void mint(),
          expires_in * 1000 * DASHBOARD_TOKEN_REMINT_FRACTION,
        );
      } catch {
        if (!cancelled)
          timer = setTimeout(() => void mint(), DASHBOARD_TOKEN_RETRY_MS);
      }
    };
    void mint();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [api, hasDashboard, name]);

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
            ...(dashboardToken
              ? [
                  {
                    type: "vesta-auth",
                    token: dashboardToken,
                    baseUrl: `${connection.url}/agents/${encodeURIComponent(name)}`,
                    agentName: name,
                  },
                ]
              : []),
          ]
        : [],
    [connection, dark, dashboardToken, name],
  );

  const sendContext = useCallback(() => {
    webView.current?.sendBridgeMessages(bridgeMessages);
  }, [bridgeMessages]);

  // Deliver a freshly-minted (or re-minted) capability to an already-loaded page.
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
            source={{ uri: dashboardUrl }}
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
