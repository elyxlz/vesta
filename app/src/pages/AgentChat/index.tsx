import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Minimize2, Wrench } from "lucide-react";
import { Chat } from "@/components/Chat";
import { AgentIsland } from "@/components/AgentIsland";
import { AgentMenu } from "@/components/AgentMenu";
import { Navbar } from "@/components/Navbar";
import { Button } from "@/components/ui/button";
import { useAgentIslandContext } from "@/lib/AgentLayout";
import { cn } from "@/lib/utils";

export function AgentChat() {
  const navigate = useNavigate();
  const { name } = useParams<{ name: string }>();
  const [showToolCalls, setShowToolCalls] = useState(false);
  const island = useAgentIslandContext();

  return (
    <div className="h-full relative">
      <div className="absolute top-0 left-0 right-0 z-10 bg-background px-3 sm:px-5 pointer-events-none">
        <div className="pointer-events-auto">
          <Navbar
            center={<AgentIsland {...island} />}
            trailing={
              <div className="flex items-center gap-1.5">
                <Button
                  size="icon-sm"
                  variant="outline"
                  className="md:size-9"
                  onClick={() => navigate(`/agent/${name}`)}
                >
                  <Minimize2 />
                </Button>
                <div data-agent-menu className="flex items-center">
                  <AgentMenu
                    open={island.menuOpen}
                    onOpenChange={island.onMenuOpenChange}
                    name={island.name}
                    info={island.info}
                    isBusy={island.isBusy}
                    authenticateBesideTrigger
                    onAuthOpen={island.handleOpenAuth}
                    onStart={island.start}
                    onStop={island.stop}
                    onRestart={island.restart}
                    onRebuild={island.rebuild}
                    onBackup={island.backup}
                    onShowBackups={island.onShowBackups}
                    onShowConsole={island.onShowConsole}
                    onShowInternals={island.onShowInternals}
                    onShowAgentSettings={island.onShowAgentSettings}
                    onOpenDeleteDialog={island.onOpenDeleteDialog}
                  />
                </div>
              </div>
            }
          />
        </div>
        <div className="flex justify-end pointer-events-auto mt-1">
          <Button
            size="icon"
            variant="ghost"
            className={cn("size-7", showToolCalls ? "text-primary" : "text-muted-foreground")}
            onClick={() => setShowToolCalls((v) => !v)}
          >
            <Wrench size={14} />
          </Button>
        </div>
      </div>
      <Chat fullscreen showToolCalls={showToolCalls} />
    </div>
  );
}
