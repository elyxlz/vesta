import { createBrowserRouter, Navigate, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { Minimize2 } from "lucide-react";
import { Connect } from "@/components/Connect";
import { Home } from "@/components/Home";
import { CreateAgent } from "@/components/CreateAgent";
import { AgentHome } from "@/components/AgentHome";
import { Chat } from "@/components/Chat";
import { DynamicIsland } from "@/components/DynamicIsland";
import { Titlebar } from "@/components/Titlebar";
import { Navbar } from "@/components/Navbar";
import { Settings } from "@/components/Settings";
import { StatusPill } from "@/components/StatusPill";
import { UpdateBar } from "@/components/UpdateBar";
import { Footer } from "@/components/Footer";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/AuthProvider";
import { useAgents } from "@/providers/AgentsProvider";
import { SelectedAgentProvider } from "@/providers/SelectedAgentProvider";

function RootLayout() {
  const { connected } = useAuth();
  const location = useLocation();

  const isConnect = location.pathname === "/connect";
  const showUpdateBar = connected && !isConnect;

  return (
    <div className="h-full bg-background flex flex-col">
      <Titlebar />
      <div className="flex flex-col flex-1 min-h-0 gap-2 px-3 sm:px-5">
        <div className="shrink-0">
          <Navbar />
          {showUpdateBar && <UpdateBar />}
        </div>
        <div className="flex-1 relative overflow-hidden min-h-0">
          <Outlet />
        </div>
        <div className="shrink-0">
          <Footer />
        </div>
      </div>
    </div>
  );
}

function AgentLayout() {
  const { connected } = useAuth();

  return (
    <div className="h-full bg-background flex flex-col">
      <Titlebar />
      <div className="flex flex-col flex-1 min-h-0 gap-3 px-3 pb-3 sm:px-5 sm:pb-5">
        <div className="shrink-0">
          <Navbar center={<DynamicIsland />} trailing={connected ? <>
            <StatusPill showHostname={false} />
            <Settings />
          </> : undefined} />
          {connected && <UpdateBar />}
        </div>
        <div className="flex-1 relative overflow-hidden min-h-0">
          <AgentHome />
        </div>
      </div>
    </div>
  );
}

function ChatFullscreenLayout() {
  const navigate = useNavigate();
  const { name } = useParams<{ name: string }>();

  return (
    <div className="h-full relative flex flex-col">
      <div className="shrink-0 z-10">
        <Titlebar />
      </div>
      <div className="flex-1 min-h-0 relative">
        <div className="absolute top-0 left-0 right-0 z-10 px-5 pointer-events-none">
          <div className="pointer-events-auto">
            <Navbar
              center={<DynamicIsland />}
              trailing={
                <Button
                  size="icon"
                  variant="ghost"
                  className="size-7 text-foreground"
                  onClick={() => navigate(`/agent/${name}`)}
                >
                  <Minimize2 size={14} />
                </Button>
              }
            />
          </div>
        </div>
        <Chat fullscreen />
      </div>
    </div>
  );
}

function NavigationGuard({ children }: { children: React.ReactNode }) {
  const { initialized, connected } = useAuth();
  const { agentsLoaded, agents } = useAgents();
  const location = useLocation();

  if (!initialized) return null;
  if (!connected) return <Navigate to="/connect" replace />;
  if (!agentsLoaded) return null;

  if (agents.length === 0 && location.pathname !== "/new") {
    return <Navigate to="/new" replace />;
  }

  const agentRouteMatch = location.pathname.match(/^\/agent\/([^/]+)/);
  if (agentRouteMatch) {
    const routeAgentName = decodeURIComponent(agentRouteMatch[1]);
    if (!agents.some((a) => a.name === routeAgentName)) {
      return <Navigate to="/" replace />;
    }
  }

  return children;
}

function RequireDisconnected({ children }: { children: React.ReactNode }) {
  const { initialized, connected } = useAuth();
  const { agentsLoaded, agents } = useAgents();

  if (!initialized) return <>{children}</>;
  if (!connected) return <>{children}</>;

  // Connected — redirect away from /connect
  if (!agentsLoaded) return null; // wait for agents before deciding
  return <Navigate to={agents.length === 0 ? "/new" : "/"} replace />;
}

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: "/connect", element: <RequireDisconnected><Connect /></RequireDisconnected> },
      {
        path: "/",
        element: (
          <NavigationGuard>
            <Outlet />
          </NavigationGuard>
        ),
        children: [
          { index: true, element: <Home /> },
          { path: "new", element: <CreateAgent /> },
        ],
      },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
  {
    path: "/agent/:name",
    element: (
      <NavigationGuard>
        <SelectedAgentProvider>
          <AgentLayout />
        </SelectedAgentProvider>
      </NavigationGuard>
    ),
  },
  {
    path: "/agent/:name/chat",
    element: (
      <NavigationGuard>
        <SelectedAgentProvider>
          <ChatFullscreenLayout />
        </SelectedAgentProvider>
      </NavigationGuard>
    ),
  },
]);
