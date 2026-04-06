import { useCallback } from "react";
import { Home, Plus } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAgents } from "@/providers/AgentsProvider";
import { useAuth } from "@/providers/AuthProvider";
import { useLayout } from "@/stores/use-layout";

import { Settings } from "@/components/Settings";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface NavbarProps {
  center?: React.ReactNode;
  trailing?: React.ReactNode;
}

export function Navbar({ center, trailing }: NavbarProps = {}) {
  const { connected } = useAuth();
  const { agents } = useAgents();
  const navigate = useNavigate();
  const location = useLocation();
  const isHome = location.pathname === "/";
  const setNavbarHeight = useLayout((s) => s.setNavbarHeight);

  const measureRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      setNavbarHeight(entry.contentRect.height);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [setNavbarHeight]);

  return (
    <div ref={measureRef} className="flex items-center justify-between min-h-11 shrink-0 select-none relative overflow-visible">
      <div className="flex-1 flex items-center">
        {connected && isHome && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => navigate("/new")}
              >
                <Plus data-icon="inline-start" />
                new agent
              </Button>
            </TooltipTrigger>
            <TooltipContent>new agent</TooltipContent>
          </Tooltip>
        )}
        {connected && agents.length > 0 && !isHome && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => navigate("/")}
              >
                <Home />
              </Button>
            </TooltipTrigger>
            <TooltipContent>home</TooltipContent>
          </Tooltip>
        )}
      </div>

      {center && (
        <div className="absolute left-1/2 top-0 bottom-0 z-30 -translate-x-1/2 flex overflow-visible">
          {center}
        </div>
      )}

      <div className="flex items-center gap-1.5">
        {trailing ?? (
          <>
            {connected && <StatusPill />}
            {connected && <Settings />}
          </>
        )}
      </div>
    </div>
  );
}
