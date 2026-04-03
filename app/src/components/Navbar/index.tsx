import { Home, Plus } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { getConnection } from "@/lib/connection";
import { useAgents } from "@/providers/AgentsProvider";
import { useAuth } from "@/providers/AuthProvider";
import { Settings } from "@/components/Settings";
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

  const hostname = (() => {
    const conn = getConnection();
    if (!conn) return "";
    try {
      return new URL(conn.url).hostname;
    } catch {
      return conn.url;
    }
  })();

  return (
    <div className="flex items-center justify-between h-11 shrink-0 select-none relative overflow-visible">
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
        <div className="absolute left-1/2 top-0 -translate-x-1/2 z-10">
          {center}
        </div>
      )}

      <div className="flex items-center gap-1.5">
        {trailing ?? (
          <>
            {connected && (
              <>
                <div className="size-2 rounded-full bg-green-500 shrink-0" />
                <span className="text-sm text-foreground truncate">{hostname}</span>
              </>
            )}
            {connected && <Settings />}
          </>
        )}
      </div>
    </div>
  );
}
