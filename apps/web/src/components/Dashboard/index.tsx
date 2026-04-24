import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutDashboard, AlertCircle } from "lucide-react";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { useTauri } from "@/providers/TauriProvider";
import { getConnection } from "@/lib/connection";
import { createServiceSession } from "@/api/service-sessions";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyMedia,
} from "@/components/ui/empty";

// Remint the session this many seconds before it actually expires, so the
// iframe never hits a dead session mid-asset-load.
const SESSION_REMINT_LEAD_SECS = 60;
// Lower bound on the remint interval, in case vestad ever reports a tiny TTL.
const SESSION_REMINT_MIN_SECS = 15;

export function Dashboard({ fullscreen }: { fullscreen?: boolean } = {}) {
  const { name, agent } = useSelectedAgent();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { resolvedTheme } = useTheme();
  const { isTauri, platform, isDesktop, isMobile, vibrancy } = useTauri();
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [iframeKey, setIframeKey] = useState(0);
  const [sessionUrl, setSessionUrl] = useState<string | null>(null);
  const handshakeRef = useRef(false);

  const dashboardService = agent.services?.dashboard;
  const hasDashboard = !!dashboardService;
  const dashboardRev = dashboardService?.rev ?? 0;
  const conn = getConnection();

  // Mint a session for the dashboard iframe. Re-mint whenever the agent,
  // skill rebuild, or connection identity changes. Falls back to the legacy
  // public path if the vestad is too old to know the /session endpoint (this
  // keeps new web app ↔ old vestad from breaking).
  useEffect(() => {
    if (!hasDashboard || !conn) {
      setSessionUrl(null);
      return;
    }

    let cancelled = false;
    let remintTimer: ReturnType<typeof setTimeout> | undefined;

    const mint = async () => {
      try {
        const session = await createServiceSession(name, "dashboard");
        if (cancelled) return;
        setError(false);
        setLoaded(false);
        setSessionUrl(`${conn.url}${session.url}`);
        setIframeKey((k) => k + 1);
        const lead = Math.max(
          SESSION_REMINT_MIN_SECS,
          session.expiresIn - SESSION_REMINT_LEAD_SECS,
        );
        remintTimer = setTimeout(mint, lead * 1000);
      } catch (err) {
        if (cancelled) return;
        // Old vestad, transient failure, or service not yet registered:
        // fall back to the legacy path. If the service is genuinely public
        // it'll load; if not, the iframe will show an auth error and the
        // user can refresh once vestad is upgraded.
        console.debug(
          "dashboard session mint failed, using legacy path:",
          err,
        );
        setSessionUrl(
          `${conn.url}/agents/${encodeURIComponent(name)}/dashboard/`,
        );
        setIframeKey((k) => k + 1);
      }
    };

    void mint();

    return () => {
      cancelled = true;
      if (remintTimer) clearTimeout(remintTimer);
    };
  }, [hasDashboard, name, dashboardRev, conn]);

  useEffect(() => {
    handshakeRef.current = false;
  }, [iframeKey]);

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
    );
  }

  if (error) {
    return (
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
    );
  }

  if (!sessionUrl) {
    return <div className="flex-1 h-full w-full bg-transparent" />;
  }

  return (
    <iframe
      key={iframeKey}
      ref={iframeRef}
      src={sessionUrl}
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
