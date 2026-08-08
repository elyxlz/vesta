import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/providers/AuthProvider";
import { useGateway } from "@/providers/GatewayProvider";

// The only routes an update leaves reachable: home, which renders the update itself, and settings,
// which is where a user goes when an update looks stuck.
const REACHABLE_WHILE_UPDATING = ["/", "/settings"];

export function NavigationGuard() {
  const { initialized, connected } = useAuth();
  const { agentsFetched, agents, updateOperation } = useGateway();
  const location = useLocation();

  if (!initialized) return null;
  if (!connected) return <Navigate to="/connect" replace />;

  // A gateway update takes over the app: agent pages are unavailable while it runs (their agent may
  // be mid-backup, and the gateway is about to restart), so everything else routes to home, which
  // renders the update.
  if (
    updateOperation !== null &&
    !REACHABLE_WHILE_UPDATING.includes(location.pathname)
  ) {
    return <Navigate to="/" replace />;
  }

  if (agentsFetched && agents.length === 0 && location.pathname !== "/new") {
    return <Navigate to="/new" replace />;
  }

  return <Outlet />;
}
