import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/providers/AuthProvider";
import { useGateway } from "@/providers/GatewayProvider";
import { NotificationsPillProvider } from "@/providers/NotificationsPillProvider";
import { loadOnboarding } from "@/lib/onboarding-progress";

// The only routes an update leaves reachable: home, which renders the update itself, and settings,
// which is where a user goes when an update looks stuck.
const REACHABLE_WHILE_UPDATING = ["/", "/settings"];

function isOnboardingAgentPath(pathname: string, agentName: string): boolean {
  const root = `/agent/${encodeURIComponent(agentName)}`;
  return pathname === root || pathname.startsWith(`${root}/`);
}

export function NavigationGuard() {
  const { initialized, connected } = useAuth();
  const { agentsFetched, agents, gatewayOperation } = useGateway();
  const location = useLocation();

  if (!initialized) return null;
  if (!connected) return <Navigate to="/connect" replace />;

  // A gateway update takes over the app: agent pages are unavailable while it runs (their agent may
  // be mid-backup, and the gateway is about to restart), so everything else routes to home, which
  // renders the update.
  if (
    gatewayOperation !== null &&
    !REACHABLE_WHILE_UPDATING.includes(location.pathname)
  ) {
    return <Navigate to="/" replace />;
  }

  // Not while an update runs: /new is unreachable then, so this redirect would ping-pong with the
  // one above, and home is the update screen regardless of the roster.
  if (
    gatewayOperation === null &&
    agentsFetched &&
    agents.length === 0 &&
    location.pathname !== "/new"
  ) {
    return <Navigate to="/new" replace />;
  }

  const onboarding = loadOnboarding();
  if (
    onboarding !== null &&
    isOnboardingAgentPath(location.pathname, onboarding.agentName)
  ) {
    const agent = agents.find(
      (candidate) => candidate.name === onboarding.agentName,
    );
    if (agent?.status !== "alive" || agent.booting !== false) {
      return <Navigate to="/new" replace />;
    }
  }

  // The pill provider lives here, above the per-route layouts, so its state
  // (queue, history cache, open surfaces) survives page navigation while the
  // navbars, and the pill they render, remount per layout.
  return (
    <NotificationsPillProvider>
      <Outlet />
    </NotificationsPillProvider>
  );
}
