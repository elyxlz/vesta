import { useCallback } from "react";
import { Home, Plus, SlidersHorizontal } from "lucide-react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useGateway } from "@/providers/GatewayProvider";
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

// ── Shell (no router dependency) ──────────────────────────────

interface NavbarProps {
  leading?: React.ReactNode;
  center?: React.ReactNode;
  trailing?: React.ReactNode;
}

export function Navbar({ leading, center, trailing }: NavbarProps) {
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
      className="absolute top-0 left-0 right-0 z-[99999] flex flex-col shrink-0 min-h-0 select-none overflow-visible px-3 pb-3.5"
      style={{ paddingTop: "calc(var(--titlebar-pt, 0.5rem) + var(--safe-area-pt, 0.5rem))" }}
    >
      <div
        data-tauri-drag-region
        className="relative flex flex-row items-center justify-between"
      >
        <div data-tauri-drag-region className="flex flex-1 items-center gap-2">
          {leading}
        </div>

        {center && (
          <div className="absolute left-1/2 top-0 bottom-0 z-[100001] flex -translate-x-1/2 items-start justify-center overflow-visible pointer-events-none" style={{ marginTop: "var(--titlebar-center-mt, 0px)" }}>
            <div className="pointer-events-auto">{center}</div>
          </div>
        )}

        <div data-tauri-drag-region className="flex items-center gap-2">
          {trailing}
        </div>
      </div>
    </div>
  );
}

// ── Router-dependent defaults ─────────────────────────────────

export function NavbarLeading() {
  const { connected } = useAuth();
  const { reachable, agentsFetched, agents } = useGateway();
  const navigate = useNavigate();
  const location = useLocation();
  const isHome = location.pathname === "/home";

  return (
    <>
      {connected && isHome && reachable && agentsFetched && (
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
      )}
      {connected && agentsFetched && agents.length > 0 && !isHome && (
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
      )}
    </>
  );
}

function AgentSettingsButton() {
  const navigate = useNavigate();
  const { name } = useParams<{ name?: string }>();
  if (!name) return null;
  return (
    <Button
      variant="default"
      className="w-full justify-start"
      onClick={() => navigate(`/agent/${encodeURIComponent(name)}/settings`)}
    >
      <SlidersHorizontal data-icon="inline-start" />
      {name}'s settings
    </Button>
  );
}

export function NavbarTrailing() {
  const { connected } = useAuth();

  return (
    <>
      {connected && <StatusPill />}
      {connected && <Settings agentSettingsSlot={<AgentSettingsButton />} />}
    </>
  );
}

// ── Composed Navbar for use inside router ─────────────────────

interface ConnectedNavbarProps {
  center?: React.ReactNode;
  trailing?: React.ReactNode;
  leading?: React.ReactNode;
}

export function ConnectedNavbar({ center, trailing, leading }: ConnectedNavbarProps) {
  return (
    <Navbar
      leading={leading ?? <NavbarLeading />}
      center={center}
      trailing={trailing ?? <NavbarTrailing />}
    />
  );
}
