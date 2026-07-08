import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { LayoutDashboard, AlertCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { useTauri } from "@/providers/TauriProvider";
import { getConnection } from "@/lib/connection";
import { openExternalUrl } from "@/lib/open-external-url";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyMedia,
} from "@/components/ui/empty";

// Pre-iframe states (no dashboard, error, loading) wear the same flat chrome as the chat card and the
// live dashboard shell — shadow-none, just the squircle + hairline ring — so the three panels are
// identical and nothing pops in when the iframe paints.
function DashboardShell({ children }: { children?: ReactNode }) {
  return (
    <div className="h-full w-full p-2">
      <Card className="relative flex h-full w-full flex-col gap-0 overflow-hidden p-0 shadow-none">
        {children}
      </Card>
    </div>
  );
}

export function Dashboard({ fullscreen }: { fullscreen?: boolean } = {}) {
  const { name, agent } = useSelectedAgent();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { resolvedTheme } = useTheme();
  const { isTauri, platform, isDesktop, isMobile, vibrancy } = useTauri();
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [iframeKey, setIframeKey] = useState(0);
  const handshakeRef = useRef(false);
  const handshakeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const dashboardService = agent.services?.dashboard;
  const hasDashboard = !!dashboardService;

  // Reset iframe when the dashboard service appears
  const prevHadDashboard = useRef(hasDashboard);
  useEffect(() => {
    if (hasDashboard && !prevHadDashboard.current) {
      setError(false);
      setLoaded(false);
      setIframeKey((k) => k + 1);
    }
    prevHadDashboard.current = hasDashboard;
  }, [hasDashboard]);

  // Reload iframe when the dashboard service is invalidated
  const dashboardRev = dashboardService?.rev ?? 0;
  const prevDashboardRev = useRef(dashboardRev);
  useEffect(() => {
    if (dashboardRev !== prevDashboardRev.current && hasDashboard) {
      setError(false);
      setLoaded(false);
      setIframeKey((k) => k + 1);
    }
    prevDashboardRev.current = dashboardRev;
  }, [dashboardRev, hasDashboard]);

  useEffect(() => {
    handshakeRef.current = false;
    return () => {
      if (handshakeTimerRef.current) clearTimeout(handshakeTimerRef.current);
    };
  }, [iframeKey]);

  // The dashboard is a non-public service: its per-service key rides in the URL
  // path so every relative sub-resource request authenticates without cookies
  // (WKWebView drops cross-origin iframe cookies). Fall back to the legacy path
  // for an older vestad that doesn't send a key.
  const conn = getConnection();
  const dashboardKey = dashboardService?.key;
  const base = conn
    ? `${conn.url}/agents/${encodeURIComponent(name)}/dashboard/`
    : null;
  const dashboardUrl =
    hasDashboard && base
      ? dashboardKey
        ? `${base}k/${encodeURIComponent(dashboardKey)}/`
        : base
      : null;

  const sendContext = useCallback(() => {
    const frame = iframeRef.current?.contentWindow;
    if (!frame) return;
    frame.postMessage(
      { type: "vesta-theme", dark: resolvedTheme === "dark" },
      "*",
    );
    frame.postMessage({ type: "vesta-layout", fullscreen: !!fullscreen }, "*");
    frame.postMessage(
      {
        type: "vesta-platform",
        isTauri,
        platform,
        isDesktop,
        isMobile,
        vibrancy,
      },
      "*",
    );
    if (conn)
      frame.postMessage(
        {
          type: "vesta-auth",
          token: conn.accessToken,
          baseUrl: `${conn.url}/agents/${encodeURIComponent(name)}`,
          agentName: name,
        },
        "*",
      );
  }, [
    resolvedTheme,
    fullscreen,
    isTauri,
    platform,
    isDesktop,
    isMobile,
    vibrancy,
    conn,
    name,
  ]);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (
        e.data?.type === "vesta-theme-request" ||
        e.data?.type === "vesta-auth-request" ||
        e.data?.type === "vesta-layout-request" ||
        e.data?.type === "vesta-platform-request"
      ) {
        handshakeRef.current = true;
        sendContext();
      }
      // Dashboard widgets can't open external URLs themselves: <a target="_blank">
      // inside an iframe is swallowed by Tauri's mobile WKWebView. Widgets post
      // { type: "vesta-open-url", url } and we route through the platform opener.
      if (e.data?.type === "vesta-open-url" && typeof e.data.url === "string") {
        const url: string = e.data.url;
        if (
          /^https?:\/\//i.test(url) ||
          /^mailto:/i.test(url) ||
          /^tel:/i.test(url)
        ) {
          void openExternalUrl(url);
        }
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [sendContext]);

  useEffect(() => {
    sendContext();
  }, [sendContext, resolvedTheme]);

  if (!hasDashboard) {
    return (
      <DashboardShell>
        <Empty className="flex-1 h-full w-full border-0">
          <EmptyHeader>
            <EmptyMedia
              variant="icon"
              className="size-12 rounded-full bg-sidebar-primary text-sidebar-primary-foreground [&_svg:not([class*='size-'])]:size-6"
            >
              <LayoutDashboard />
            </EmptyMedia>
            <EmptyTitle>your dashboard</EmptyTitle>
            <EmptyDescription>
              ask your agent to set up the dashboard and add some widgets
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </DashboardShell>
    );
  }

  if (error) {
    return (
      <DashboardShell>
        <Empty className="flex-1 h-full w-full border-0">
          <EmptyHeader>
            <EmptyMedia
              variant="icon"
              className="size-12 rounded-full bg-sidebar-primary text-sidebar-primary-foreground [&_svg:not([class*='size-'])]:size-6"
            >
              <AlertCircle />
            </EmptyMedia>
            <EmptyTitle>dashboard unavailable</EmptyTitle>
            <EmptyDescription>
              the dashboard server isn't responding — ask your agent to check on
              it
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </DashboardShell>
    );
  }

  return (
    <div className="relative h-full w-full">
      {!loaded && (
        <div className="absolute inset-0">
          <DashboardShell />
        </div>
      )}
      <iframe
        key={iframeKey}
        ref={iframeRef}
        src={dashboardUrl!}
        allow="microphone; camera; display-capture; autoplay; fullscreen; picture-in-picture; clipboard-read; clipboard-write; geolocation; screen-wake-lock; web-share; payment; publickey-credentials-get; publickey-credentials-create; encrypted-media; midi; gamepad; xr-spatial-tracking; hid; serial; usb; bluetooth; idle-detection; local-fonts; storage-access; compute-pressure; window-management"
        className={`w-full h-full bg-transparent transition-opacity duration-200 ${loaded ? "opacity-100" : "opacity-0"}`}
        onLoad={() => {
          sendContext();
          if (handshakeRef.current) {
            setLoaded(true);
          } else {
            if (handshakeTimerRef.current)
              clearTimeout(handshakeTimerRef.current);
            handshakeTimerRef.current = setTimeout(() => {
              handshakeTimerRef.current = null;
              if (handshakeRef.current) {
                setLoaded(true);
              } else {
                setError(true);
              }
            }, 500);
          }
        }}
        onError={() => setError(true)}
      />
    </div>
  );
}
