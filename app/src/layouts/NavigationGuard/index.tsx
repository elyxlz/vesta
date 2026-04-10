import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/providers/AuthProvider";
import { useGateway } from "@/providers/GatewayProvider";

export function NavigationGuard() {
  const { initialized, connected } = useAuth();
  const { agentsFetched, agents } = useGateway();
  const location = useLocation();

  if (!initialized) return null;
  if (!connected) return <Navigate to="/connect" replace />;
  if (!agentsFetched) return null;

  if (agents.length === 0 && location.pathname !== "/new") {
    return <Navigate to="/new" replace />;
  }

  return <Outlet />;
}
