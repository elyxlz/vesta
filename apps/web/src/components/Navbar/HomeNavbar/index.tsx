import { useLocation, useNavigate } from "react-router-dom";
import { Home, Plus } from "lucide-react";
import { SettingsButton } from "@/components/Settings";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { useGateway } from "@/providers/GatewayProvider";
import { useOnboarding } from "@/stores/use-onboarding";
import { useToast } from "@/stores/use-toast";
import { LogoText } from "@/components/Logo/LogoText";
import { Navbar } from "..";

function Leading() {
  const navigate = useNavigate();
  const location = useLocation();
  const { reachable, agentsFetched, agents } = useGateway();
  const onboardingStep = useOnboarding((s) => s.step);
  const toast = useToast();

  const isHome = location.pathname === "/";
  const isNew = location.pathname === "/new";

  // Rendered whenever the gateway is unreachable too, but a click then raises a toast
  // instead of routing into the create flow that needs a live gateway.
  if (isHome && (!reachable || agentsFetched)) {
    return (
      <Button
        variant="outline"
        size="icon-lg"
        aria-label="new agent"
        onClick={() => {
          if (!reachable) {
            toast.error("can't reach the gateway right now");
            return;
          }
          void navigate("/new");
        }}
      >
        <Plus />
      </Button>
    );
  }

  if (isNew && agents.length > 0 && onboardingStep === "name") {
    return (
      <Button
        variant="outline"
        size="icon-lg"
        aria-label="home"
        onClick={() => {
          void navigate("/");
        }}
      >
        <Home />
      </Button>
    );
  }

  return null;
}

export function HomeNavbar() {
  // The gear is hidden while unreachable: the disconnected overlay takes over and
  // routing to /settings would render it underneath that overlay.
  const { reachable } = useGateway();

  return (
    <Navbar
      leading={<Leading />}
      center={<LogoText className="-translate-y-1" />}
      trailing={
        <>
          <StatusPill showHostname={false} />
          {reachable && <SettingsButton />}
        </>
      }
    />
  );
}
