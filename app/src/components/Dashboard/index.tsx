import { useEffect, useRef, useCallback, useState } from "react";
import { LayoutDashboard, AlertCircle } from "lucide-react";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useTheme } from "@/stores/use-theme";
import { getConnection } from "@/lib/connection";
import { apiFetch } from "@/api/client";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyMedia,
} from "@/components/ui/empty";

const POLL_INTERVAL = 5_000;

type Status = "loading" | "not-setup" | "ready" | "error";

export function Dashboard() {
  const { name } = useSelectedAgent();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const theme = useTheme((s) => s.theme);
  const resolved = useTheme((s) => s.resolved);
  const [status, setStatus] = useState<Status>("loading");
  const [loaded, setLoaded] = useState(false);

  // Poll services endpoint until dashboard is registered
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function check() {
      try {
        const resp = await apiFetch(`/agents/${encodeURIComponent(name)}/services`);
        if (cancelled) return;
        const body: { services: Record<string, number> } = await resp.json();
        const registered = "dashboard" in body.services;
        setStatus(registered ? "ready" : "not-setup");
        if (!registered) {
          timer = setTimeout(check, POLL_INTERVAL);
        }
      } catch {
        if (!cancelled) {
          setStatus("not-setup");
          timer = setTimeout(check, POLL_INTERVAL);
        }
      }
    }

    check();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [name]);

  const conn = getConnection();
  const dashboardUrl =
    status === "ready" && conn
      ? `${conn.url}/agents/${encodeURIComponent(name)}/dashboard/?token=${encodeURIComponent(conn.accessToken)}`
      : null;

  const sendTheme = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage(
      { type: "vesta-theme", dark: resolved() === "dark" },
      "*",
    );
  }, [resolved]);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "vesta-theme-request") sendTheme();
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [sendTheme]);

  useEffect(() => {
    sendTheme();
  }, [sendTheme, theme]);

  if (status === "loading") return null;

  if (status === "not-setup") {
    return (
      <Empty className="flex-1 border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
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
      <Empty className="flex-1 border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <AlertCircle />
          </EmptyMedia>
          <EmptyTitle>dashboard unavailable</EmptyTitle>
          <EmptyDescription>
            the dashboard server isn't responding — ask your agent to check on it
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <iframe
      ref={iframeRef}
      src={dashboardUrl!}
      className={`w-full h-full border-0 bg-transparent transition-opacity duration-200 ${loaded ? "opacity-100" : "opacity-0"}`}
      onLoad={() => {
        sendTheme();
        setLoaded(true);
      }}
      onError={() => setStatus("error")}
      title="Dashboard"
    />
  );
}
