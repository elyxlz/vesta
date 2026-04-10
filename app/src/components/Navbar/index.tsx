import { useCallback } from "react";
import { Home, Plus } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useGateway } from "@/providers/GatewayProvider";
import { useAuth } from "@/providers/AuthProvider";
import { useLayout } from "@/stores/use-layout";

import { Settings } from "@/components/Settings";
import { StatusPill } from "@/components/StatusPill";
import { UpdateBar } from "@/components/UpdateBar";
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
  const { connected } = useAuth();
  const { agents } = useGateway();
  const navigate = useNavigate();
  const location = useLocation();
  const isHome = location.pathname === "/home";
  const setNavbarHeight = useLayout((s) => s.setNavbarHeight);

  const measureRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      const border = entry.borderBoxSize[0];
      const height = border
        ? border.blockSize
        : entry.target.getBoundingClientRect().height;
      setNavbarHeight(height);
    });
    observer.observe(node);
  }, [setNavbarHeight]);

  return (
    <div
      ref={measureRef}
      data-tauri-drag-region
      className="absolute top-0 left-0 right-0 z-[99999] flex flex-col shrink-0 min-h-0 select-none overflow-visible p-3"
    >
      <div
        data-tauri-drag-region
        className="relative flex flex-row items-center justify-between"
      >
        <div data-tauri-drag-region className="flex flex-1 items-center gap-2">
          {connected && isHome && (
            <Button
              variant="secondary"
              size="lg"
              onClick={() => navigate("/new")}
            >
              <Plus data-icon="inline-start" />
              new agent
            </Button>
          )}
          {connected && agents.length > 0 && !isHome && (
            <ButtonGroup>
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
            </ButtonGroup>
          )}
          {leadingExtra}
        </div>

        {center && (
          <div className="absolute left-1/2 top-0 bottom-0 z-[100001] flex -translate-x-1/2 items-start justify-center overflow-visible">
            {center}
          </div>
        )}

        <div data-tauri-drag-region className="flex items-center gap-2">
          {trailing ?? (
            <>
              {connected && <StatusPill />}
              {connected && <Settings />}
            </>
          )}
        </div>
      </div>
      <UpdateBar />
    </div>
  );
}
