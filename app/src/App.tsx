import { useEffect } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Titlebar } from "@/components/Titlebar";
import { UpdateBar } from "@/components/UpdateBar";
import { Connect } from "@/components/Connect";
import { Home } from "@/components/Home";
import { CreateAgent } from "@/components/CreateAgent";
import { AgentDetail } from "@/components/AgentDetail";
import { Chat } from "@/components/Chat";
import { Console } from "@/components/Console";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useAppStore } from "@/stores/use-app-store";
import { useNavigation, parseUrl } from "@/stores/use-navigation";
import { useVersion } from "@/hooks/use-version";
import "@/stores/use-theme";
import { autoSetup } from "@/api";
import { getConnection } from "@/lib/connection";
import { isTauri } from "@/lib/env";

function AppContent() {
  const view = useNavigation((s) => s.view);
  const navigateToConnect = useNavigation((s) => s.navigateToConnect);
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
        navigateToConnect();
        return;
      }

      try {
        const resp = await fetch(`${conn.url}/health`, {
          headers: { Authorization: `Bearer ${conn.apiKey}` },
        });
        if (resp.ok) {
          setConnected(true);
          const { view: urlView, agent } = parseUrl();
          if (urlView !== "connect" && urlView !== "loading") {
            useNavigation.setState({ view: urlView, selectedAgent: agent });
          } else {
            useNavigation.getState().navigateHome();
          }
        } else {
          navigateToConnect();
        }
      } catch {
        navigateToConnect();
      }
    };

    init();
  }, [navigateToConnect, setConnected]);

  if (view === "loading") return null;

  const showUpdateBar =
    connected && (view === "home" || view === "agent-detail" || view === "create-agent");

  return (
    <div className="flex flex-col h-full bg-background">
      <Titlebar />
      {showUpdateBar && <UpdateBar />}

      <div className="flex-1 relative overflow-hidden h-0">
        {view === "connect" && <Connect />}
        {view === "home" && <Home />}
        {view === "create-agent" && <CreateAgent />}
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

export function App() {
  return (
    <TooltipProvider delayDuration={300}>
      <AppContent />
    </TooltipProvider>
  );
}
