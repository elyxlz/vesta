import { AgentHome } from "@/components/AgentHome";
import { AgentIsland } from "@/components/AgentIsland";
import { AgentMenu } from "@/components/AgentMenu";
import { Navbar } from "@/components/Navbar";
import { UpdateBar } from "@/components/UpdateBar";
import { useAgentIslandContext } from "@/lib/AgentLayout";
import { useAuth } from "@/providers/AuthProvider";

export function AgentDashboard() {
  const { connected } = useAuth();
  const island = useAgentIslandContext();

  return (
    <div className="flex flex-col flex-1 min-h-0 gap-3 md:gap-4 px-3 pb-3 sm:px-5 sm:pb-5">
      <div className="shrink-0">
        <Navbar
          center={<AgentIsland {...island} />}
          trailing={
            connected ? (
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
            ) : undefined
          }
        />
        {connected && <UpdateBar />}
      </div>
      <div className="flex-1 relative overflow-hidden min-h-0 outline outline-2 outline-red-500 outline-offset-0">
        <AgentHome />
      </div>
    </div>
  );
}
