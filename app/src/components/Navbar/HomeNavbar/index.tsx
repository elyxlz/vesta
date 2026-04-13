import { useLocation, useNavigate } from "react-router-dom";
import { Home, Plus } from "lucide-react";
import { Settings } from "@/components/Settings";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useGateway } from "@/providers/GatewayProvider";
import { useOnboarding } from "@/stores/use-onboarding";
import { LogoText } from "@/components/Logo/LogoText";
import { Navbar } from "..";

function Leading() {
  const navigate = useNavigate();
  const location = useLocation();
  const { reachable, agentsFetched, agents } = useGateway();
  const onboardingStep = useOnboarding((s) => s.step);

  const isHome = location.pathname === "/home";
  const isNew = location.pathname === "/new";

  if (isHome && reachable && agentsFetched) {
    return (
      <>
        <Button
          variant="secondary"
          size="lg"
          onClick={() => navigate("/new")}
          className="max-sm:hidden"
        >
          <Plus data-icon="inline-start" />
          new agent
        </Button>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon-lg"
              onClick={() => navigate("/new")}
              className="sm:hidden"
            >
              <Plus />
            </Button>
          </TooltipTrigger>
          <TooltipContent>new agent</TooltipContent>
        </Tooltip>
      </>
    );
  }

  if (isNew && agents.length > 0 && onboardingStep === "name") {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            size="icon-lg"
            onClick={() => navigate("/home")}
          >
            <Home />
          </Button>
        </TooltipTrigger>
        <TooltipContent>home</TooltipContent>
      </Tooltip>
    );
  }

  return null;
}

export function HomeNavbar() {
  return (
    <Navbar
      leading={<Leading />}
      center={
        <LogoText />
      }
      trailing={
        <>
          <StatusPill />
          <Settings />
        </>
      }
    />
  );
}
