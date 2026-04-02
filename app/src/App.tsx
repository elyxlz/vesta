import { useEffect } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Titlebar } from "@/components/Titlebar";
import { UpdateBar } from "@/components/UpdateBar";
import { Connect } from "@/components/Connect";
import { Home } from "@/components/Home";
import { AgentDetail } from "@/components/AgentDetail";
import { Chat } from "@/components/Chat";
import { Console } from "@/components/Console";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useAppStore } from "@/stores/use-app-store";
import { useNavigation } from "@/stores/use-navigation";
import { useVersion } from "@/hooks/use-version";
import "@/stores/use-theme";
import { autoSetup } from "@/api";
import { getConnection } from "@/lib/connection";
import { isTauri } from "@/lib/env";

function AppContent() {
  const view = useNavigation((s) => s.view);
  const setView = useNavigation((s) => s.setView);
  const setConnected = useAppStore((s) => s.setConnected);
  const connected = useAppStore((s) => s.connected);

  useVersion();

  useEffect(() => {
    const init = async () => {
      try {
        await autoSetup();
      } catch {
        // auto_setup is optional
      }

      if (isTauri) {
        try {
          const { getCurrentWindow } = await import("@tauri-apps/api/window");
          const win = getCurrentWindow();
          const monitor = await import("@tauri-apps/api/window").then((m) =>
            m.currentMonitor(),
          );
          if (monitor) {
            const shortest = Math.min(
              monitor.size.width / monitor.scaleFactor,
              monitor.size.height / monitor.scaleFactor,
            );
            const size = Math.round(
              Math.max(400, Math.min(800, shortest * 0.6)),
            );
            await win.setSize(
              new (await import("@tauri-apps/api/dpi")).LogicalSize(size, size),
            );
            await win.center();
          }
        } catch {
          // ignore sizing errors
        }
      }

      const conn = getConnection();
      if (!conn) {
        setView("connect");
        return;
      }

      try {
        const resp = await fetch(`${conn.url}/health`, {
          headers: { Authorization: `Bearer ${conn.apiKey}` },
        });
        if (resp.ok) {
          setConnected(true);
          setView("home");
        } else {
          setView("connect");
        }
      } catch {
        setView("connect");
      }
    };

    init();
  }, [setView, setConnected]);

  const showUpdateBar =
    connected && (view === "home" || view === "agent-detail");

  return (
    <div
      className="flex flex-col h-full"
      style={{ background: "var(--color-background)" }}
    >
      <Titlebar />
      {showUpdateBar && <UpdateBar />}

      <div className="flex-1 relative overflow-hidden h-0">
        {view === "loading" && <LoadingView />}
        {view === "connect" && <Connect />}
        {view === "home" && <Home />}
        {(view === "agent-detail" ||
          view === "agent-chat" ||
          view === "agent-console") && (
          <>
            <AgentDetail />
            {view === "agent-chat" && <Chat />}
            {view === "agent-console" && <Console />}
          </>
        )}

        {view !== "agent-chat" && view !== "agent-console" && (
          <div className="absolute bottom-3 right-3 z-20">
            <ThemeToggle />
          </div>
        )}
      </div>
    </div>
  );
}

function LoadingView() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 animate-view-in">
      <div className="w-10 h-10 rounded-full bg-gradient-to-b from-[#b8ceb0] to-[#5a7e50] animate-breathe" />
      <span className="text-[11px] text-muted">loading...</span>
    </div>
  );
}

export function App() {
  return (
    <TooltipProvider delayDuration={300}>
      <AppContent />
    </TooltipProvider>
  );
}
