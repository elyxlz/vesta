import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { LayoutDashboard, AlertCircle } from "lucide-react";
import { serviceKeyPathUrl } from "@vesta/core";
import { useServiceKey } from "@vesta/core/react";
import { Card } from "@/components/ui/card";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { useRuntime } from "@/providers/RuntimeProvider";
import { getConnection } from "@/lib/connection";
import { serviceKeys } from "@/lib/service-key-cache";
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

// The frame's identity: which document, under which credential. A change means the mounted
// document is stale (the service appeared, was invalidated, or its key rotated, since the
// document loaded under the old credential), so the keyed iframe remounts and the load and
// handshake state reset with it.
function frameIdentityOf(
  hasDashboard: boolean,
  rev: number,
  key: string | null,
): string {
  return `${hasDashboard ? "up" : "down"}:${String(rev)}:${key ?? ""}`;
}

export function Dashboard({ fullscreen }: { fullscreen?: boolean } = {}) {
  const { name, agent } = useSelectedAgent();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { resolvedTheme } = useTheme();
  const { isDesktopApp, platform, isDesktop, isMobile, vibrancy } =
    useRuntime();
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const handshakeRef = useRef(false);
  const handshakeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const dashboardService = agent.services.dashboard;
  const hasDashboard = !!dashboardService;
  const dashboardRev = dashboardService?.rev ?? 0;

  const conn = getConnection();
  // The dashboard is a private service, so the frame authenticates with a minted service key
  // carried in the path: an iframe document sends no header, and its relative asset requests
  // inherit neither a header nor a query string.
  const { key: dashboardKey, error: keyError } = useServiceKey(
    serviceKeys,
    name,
    "dashboard",
    hasDashboard,
  );
  const dashboardUrl =
    hasDashboard && conn && dashboardKey
      ? serviceKeyPathUrl(conn.url, name, "dashboard", dashboardKey)
      : null;

  const frameIdentity = frameIdentityOf(
    hasDashboard,
    dashboardRev,
    dashboardKey,
  );
  const prevFrameIdentity = useRef(frameIdentity);
  useEffect(() => {
    if (prevFrameIdentity.current === frameIdentity) return;
    prevFrameIdentity.current = frameIdentity;
    if (handshakeTimerRef.current) clearTimeout(handshakeTimerRef.current);
    handshakeTimerRef.current = null;
    handshakeRef.current = false;
    setError(false);
    setLoaded(false);
  }, [frameIdentity]);

  useEffect(() => {
    return () => {
      if (handshakeTimerRef.current) clearTimeout(handshakeTimerRef.current);
    };
  }, []);

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
        isDesktopApp,
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
    isDesktopApp,
    platform,
    isDesktop,
    isMobile,
    vibrancy,
    conn,
    name,
  ]);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      const data: unknown = e.data;
      if (typeof data !== "object" || data === null || !("type" in data))
        return;
      if (
        data.type === "vesta-theme-request" ||
        data.type === "vesta-auth-request" ||
        data.type === "vesta-layout-request" ||
        data.type === "vesta-platform-request"
      ) {
        handshakeRef.current = true;
        sendContext();
      }
      // Dashboard widgets can't open external URLs themselves: the desktop
      // app's window-open handler owns navigation. Widgets post
      // { type: "vesta-open-url", url } and we route through the platform opener.
      if (
        data.type === "vesta-open-url" &&
        "url" in data &&
        typeof data.url === "string"
      ) {
        const url = data.url;
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

  if (error || keyError != null) {
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
      {(!loaded || !dashboardUrl) && (
        <div className="absolute inset-0">
          <DashboardShell />
        </div>
      )}
      {dashboardUrl && (
        <iframe
          key={frameIdentity}
          ref={iframeRef}
          src={dashboardUrl}
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
      )}
    </div>
  );
}
