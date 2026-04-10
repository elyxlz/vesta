import { useEffect, useRef, useCallback, useState } from "react";
import { LayoutDashboard, AlertCircle } from "lucide-react";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useTheme } from "@/providers/ThemeProvider";
import { getConnection } from "@/lib/connection";
import { apiFetch } from "@/api/client";
import { useServiceUpdate } from "@/hooks/use-service-update";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyMedia,
} from "@/components/ui/empty";

type Status = "loading" | "not-setup" | "ready" | "error";

export function Dashboard({ fullscreen }: { fullscreen?: boolean } = {}) {
  const { name } = useSelectedAgent();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { resolvedTheme } = useTheme();
  const [status, setStatus] = useState<Status>("loading");
  const [loaded, setLoaded] = useState(false);
  const [iframeKey, setIframeKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const resp = await apiFetch(
          `/agents/${encodeURIComponent(name)}/services`,
        );
        if (cancelled) return;
        const body: { services: Record<string, number> } = await resp.json();
        setStatus("dashboard" in body.services ? "ready" : "not-setup");
      } catch {
        if (!cancelled) setStatus("not-setup");
      }
    }
    check();
    return () => {
      cancelled = true;
    };
  }, [name]);

  useServiceUpdate(
    "dashboard",
    useCallback((action) => {
      if (action === "removed") {
        setStatus("not-setup");
      } else {
        setStatus("ready");
        setLoaded(false);
        setIframeKey((k) => k + 1);
      }
    }, []),
  );

  const conn = getConnection();
  const dashboardUrl =
    status === "ready" && conn
      ? `${conn.url}/agents/${encodeURIComponent(name)}/dashboard/?token=${encodeURIComponent(conn.accessToken)}`
      : null;

  const sendContext = useCallback(() => {
    const frame = iframeRef.current?.contentWindow;
    if (!frame) return;
    frame.postMessage(
      { type: "vesta-theme", dark: resolvedTheme === "dark" },
      "*",
    );
    frame.postMessage({ type: "vesta-layout", fullscreen: !!fullscreen }, "*");
    if (conn)
      frame.postMessage(
        {
          type: "vesta-auth",
          token: conn.accessToken,
          baseUrl: `${conn.url}/agents/${encodeURIComponent(name)}`,
        },
        "*",
      );
  }, [resolvedTheme, conn, fullscreen]);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (
        e.data?.type === "vesta-theme-request" ||
        e.data?.type === "vesta-auth-request" ||
        e.data?.type === "vesta-layout-request"
      ) {
        sendContext();
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [sendContext]);

  useEffect(() => {
    sendContext();
  }, [sendContext, resolvedTheme]);

  if (status === "loading") return null;

  if (status === "not-setup") {
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

  if (status === "error") {
    return (
      <Empty className="flex-1 h-full w-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
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
      className={`w-full h-full bg-transparent transition-opacity duration-200 ${loaded ? "opacity-100" : "opacity-0"}`}
      onLoad={() => {
        sendContext();
        setLoaded(true);
      }}
      onError={() => setStatus("error")}
    />
  );
}
