import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutDashboard, AlertCircle } from "lucide-react";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { useTauri } from "@/providers/TauriProvider";
import { getConnection } from "@/lib/connection";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyMedia,
} from "@/components/ui/empty";

export function Dashboard({ fullscreen }: { fullscreen?: boolean } = {}) {
  const { name, agent } = useSelectedAgent();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { resolvedTheme } = useTheme();
  const { isTauri, platform, isDesktop, isMobile, vibrancy } = useTauri();
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [iframeKey, setIframeKey] = useState(0);
  const handshakeRef = useRef(false);

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
  }, [iframeKey]);

  const conn = getConnection();
  const dashboardUrl =
    hasDashboard && conn
      ? `${conn.url}/agents/${encodeURIComponent(name)}/dashboard/`
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
      { type: "vesta-platform", isTauri, platform, isDesktop, isMobile, vibrancy },
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
  }, [resolvedTheme, fullscreen, isTauri, platform, isDesktop, isMobile, vibrancy, conn, name]);

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
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [sendContext]);

  useEffect(() => {
    sendContext();
  }, [sendContext, resolvedTheme]);

  if (!hasDashboard) {
    return (
      <Empty className="flex-1 h-full w-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon" className="size-12 rounded-full bg-sidebar-primary text-sidebar-primary-foreground [&_svg:not([class*='size-'])]:size-6">
            <LayoutDashboard />
          </EmptyMedia>
          <EmptyTitle>your dashboard</EmptyTitle>
          <EmptyDescription>
            ask your agent to set up the dashboard and add some widgets
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (error) {
    return (
      <Empty className="flex-1 h-full w-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon" className="size-12 rounded-full bg-sidebar-primary text-sidebar-primary-foreground [&_svg:not([class*='size-'])]:size-6">
            <AlertCircle />
          </EmptyMedia>
          <EmptyTitle>dashboard unavailable</EmptyTitle>
          <EmptyDescription>
            the dashboard server isn't responding — ask your agent to check on
            it
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
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
          setTimeout(() => {
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
  );
}
