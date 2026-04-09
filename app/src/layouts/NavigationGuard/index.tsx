import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/providers/AuthProvider";
import { useAgents } from "@/providers/AgentsProvider";

export function NavigationGuard() {
  const { initialized, connected } = useAuth();
  const { agentsLoaded, agents } = useAgents();
  const location = useLocation();

  if (!initialized) return null;
  if (!connected) return <Navigate to="/connect" replace />;
  if (!agentsLoaded) return null;

  if (agents.length === 0 && location.pathname !== "/new") {
    return <Navigate to="/new" replace />;
  }

  return <Outlet />;
}
