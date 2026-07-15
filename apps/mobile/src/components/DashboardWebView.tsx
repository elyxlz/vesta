import { forwardRef, useImperativeHandle, useRef } from "react";
import { Platform, type StyleProp, type ViewStyle } from "react-native";
import IOSWebView from "react-native-webview/lib/WebView.ios";
import AndroidWebView from "react-native-webview/lib/WebView.android";
import type {
  ShouldStartLoadRequest,
  WebViewErrorEvent,
  WebViewMessageEvent,
  WebViewSource,
} from "react-native-webview/lib/WebViewTypes";

function serializeForInjection(value: unknown): string {
  return JSON.stringify(value)
    .replaceAll("<", "\\u003c")
    .replaceAll("\u2028", "\\u2028")
    .replaceAll("\u2029", "\\u2029");
}

function embeddedDocumentSetup(
  dark: boolean,
  bridgeMessages: readonly Record<string, unknown>[],
): string {
  const serializedMessages = serializeForInjection(bridgeMessages);
  return `
    (() => {
      const root = document.documentElement;
      root.classList.toggle("dark", ${dark});
      root.style.colorScheme = "${dark ? "dark" : "light"}";

      if (!document.getElementById("vesta-mobile-embed")) {
        const style = document.createElement("style");
        style.id = "vesta-mobile-embed";
        style.textContent = \`
          [data-fullscreen] {
            margin: 0 !important;
            width: 100% !important;
            height: 100% !important;
            border-radius: 0 !important;
            box-shadow: none !important;
          }
        \`;
        (document.head || root).appendChild(style);
      }

      const sendContext = () => {
        const messages = ${serializedMessages};
        for (const data of messages) {
          window.dispatchEvent(new MessageEvent("message", { data }));
        }
      };

      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", sendContext, {
          once: true,
        });
      } else {
        sendContext();
      }
    })();
    true;
  `;
}

export interface DashboardWebViewHandle {
  postMessage: (message: string) => void;
}

interface DashboardWebViewProps {
  bridgeMessages: readonly Record<string, unknown>[];
  dark: boolean;
  source: WebViewSource;
  style?: StyleProp<ViewStyle>;
  containerStyle?: StyleProp<ViewStyle>;
  originWhitelist?: string[];
  onLoad?: () => void;
  onMessage?: (event: WebViewMessageEvent) => void;
  onShouldStartLoadWithRequest?: (request: ShouldStartLoadRequest) => boolean;
  onError?: (event: WebViewErrorEvent) => void;
}

export const DashboardWebView = forwardRef<
  DashboardWebViewHandle,
  DashboardWebViewProps
>(function DashboardWebView(
  { bridgeMessages, dark, ...props },
  forwardedRef,
) {
  const nativeRef = useRef<DashboardWebViewHandle>(null);
  useImperativeHandle(
    forwardedRef,
    () => ({
      postMessage: (message) => nativeRef.current?.postMessage(message),
    }),
    [],
  );

  const sharedProps = {
    ...props,
    ref: nativeRef,
    automaticallyAdjustContentInsets: false,
    contentInsetAdjustmentBehavior: "never" as const,
    contentInset: { top: 0, right: 0, bottom: 0, left: 0 },
    injectedJavaScriptBeforeContentLoaded: embeddedDocumentSetup(
      dark,
      bridgeMessages,
    ),
    injectedJavaScript: embeddedDocumentSetup(dark, bridgeMessages),
    sharedCookiesEnabled: true,
    allowsInlineMediaPlayback: true,
    mediaPlaybackRequiresUserAction: false,
  };
  return Platform.OS === "ios" ? (
    <IOSWebView {...sharedProps} />
  ) : (
    <AndroidWebView {...sharedProps} />
  );
});
