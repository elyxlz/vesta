import { forwardRef, useState, type ComponentProps } from "react";
import { StyleSheet, View } from "react-native";
import {
  DashboardWebView as ProductionDashboardWebView,
  type DashboardWebViewHandle,
} from "../../src/components/DashboardWebView";

export type { DashboardWebViewHandle } from "../../src/components/DashboardWebView";

type DashboardWebViewProps = ComponentProps<typeof ProductionDashboardWebView>;

// Maestro reads the native accessibility tree, which does not reliably expose
// text rendered inside a WebView on Android. onLoad is a native RN callback, so
// this marker is a deterministic "content painted" signal the flows wait on
// instead of racing the WebView's inner text.
const DASHBOARD_READY_LABEL = "Dashboard ready";

function dashboardDocument(dark: boolean): string {
  const background = dark ? "#111114" : "#f6f5f2";
  const card = dark ? "#1d1d22" : "#ffffff";
  const text = dark ? "#f5f5f7" : "#1d1d1f";
  const muted = dark ? "#aaa8b2" : "#6d6974";
  const border = dark ? "#34343c" : "#e5e1e8";
  return `<!doctype html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
    <style>
      * { box-sizing: border-box; }
      body {
        margin: 0;
        padding: 22px 18px 36px;
        background: ${background};
        color: ${text};
        font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      }
      .kicker {
        color: #7463d8;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: .08em;
        text-transform: uppercase;
      }
      h1 { margin: 5px 0 6px; font-size: 27px; letter-spacing: -.04em; }
      .intro { margin: 0 0 20px; color: ${muted}; font-size: 14px; line-height: 1.4; }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 11px; }
      .card {
        min-height: 112px;
        border: 1px solid ${border};
        border-radius: 18px;
        padding: 15px;
        background: ${card};
      }
      .wide { grid-column: 1 / -1; min-height: auto; }
      .label { color: ${muted}; font-size: 12px; }
      .value { margin-top: 10px; font-size: 27px; font-weight: 700; letter-spacing: -.04em; }
      .status { display: flex; align-items: center; gap: 8px; margin-top: 12px; font-size: 14px; }
      .dot { width: 9px; height: 9px; border-radius: 50%; background: #52b788; }
      ul { margin: 12px 0 0; padding: 0; list-style: none; }
      li { padding: 9px 0; border-top: 1px solid ${border}; font-size: 14px; }
      li:first-child { border-top: 0; padding-top: 0; }
    </style>
  </head>
  <body data-fullscreen>
    <span class="kicker">Aria dashboard</span>
    <h1>Today at a glance</h1>
    <p class="intro">A focused overview of current work and agent health.</p>
    <div class="grid">
      <section class="card">
        <div class="label">Active goals</div>
        <div class="value">3</div>
      </section>
      <section class="card">
        <div class="label">Completed today</div>
        <div class="value">7</div>
      </section>
      <section class="card wide">
        <div class="label">Agent health</div>
        <div class="status"><span class="dot"></span>All systems ready</div>
      </section>
      <section class="card wide">
        <div class="label">Next up</div>
        <ul>
          <li>Review onboarding screenshots</li>
          <li>Prepare Monday product notes</li>
          <li>Check release readiness</li>
        </ul>
      </section>
    </div>
  </body>
</html>`;
}

export const DashboardWebView = forwardRef<
  DashboardWebViewHandle,
  DashboardWebViewProps
>(function VisualDashboardWebView({ dark, source, onLoad, ...props }, forwardedRef) {
  const baseUrl = "uri" in source ? source.uri : "https://home.vesta.run/";
  const [loaded, setLoaded] = useState(false);
  return (
    <>
      <ProductionDashboardWebView
        {...props}
        ref={forwardedRef}
        dark={dark}
        source={{
          html: dashboardDocument(dark),
          baseUrl,
        }}
        onLoad={() => {
          setLoaded(true);
          onLoad?.();
        }}
      />
      {loaded ? (
        <View
          accessible
          accessibilityLabel={DASHBOARD_READY_LABEL}
          style={styles.readyMarker}
        />
      ) : null}
    </>
  );
});

const styles = StyleSheet.create({
  readyMarker: { position: "absolute", top: 0, left: 0, width: 4, height: 4 },
});
