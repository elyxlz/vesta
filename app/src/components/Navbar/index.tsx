import { useCallback } from "react";
import { Home, Plus } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAgents } from "@/providers/AgentsProvider";
import { useAuth } from "@/providers/AuthProvider";
import { useLayout } from "@/stores/use-layout";
import { useTauri } from "@/providers/TauriProvider";

import { Settings } from "@/components/Settings";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface NavbarProps {
  center?: React.ReactNode;
  trailing?: React.ReactNode;
  leadingExtra?: React.ReactNode;
}

export function Navbar({ center, trailing, leadingExtra }: NavbarProps = {}) {
  const { isTauri, isMacOS } = useTauri();
  const { connected } = useAuth();
  const { agents } = useAgents();
  const navigate = useNavigate();
  const location = useLocation();
  const isHome = location.pathname === "/home";
  const setNavbarHeight = useLayout((s) => s.setNavbarHeight);

  const measureRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      const border = entry.borderBoxSize[0];
      const height = border ? border.blockSize : entry.target.getBoundingClientRect().height;
      setNavbarHeight(height);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [setNavbarHeight]);

  return (
    <div
      ref={measureRef}
      data-tauri-drag-region
      className={`flex shrink-0 flex-col overflow-visible ${isTauri && isMacOS ? "pt-8" : "pt-5"} select-none`}
    >
      <div data-tauri-drag-region className="relative flex h-11 w-full min-h-0 items-center justify-between">
        <div data-tauri-drag-region className="flex flex-1 items-center gap-2">
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
            <ButtonGroup>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    className="md:size-9"
                    onClick={() => navigate("/home")}
                  >
                    <Home />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>home</TooltipContent>
              </Tooltip>
            </ButtonGroup>
          )}
          {leadingExtra}
        </div>

        {center && (
          <div className="absolute left-1/2 top-0 bottom-0 z-[99999] flex -translate-x-1/2 items-start justify-center overflow-visible">
            {center}
          </div>
        )}

        <div data-tauri-drag-region className="flex items-center gap-1.5">
          {trailing ?? (
            <>
              {connected && <StatusPill />}
              {connected && <Settings />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
