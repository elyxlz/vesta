import { useNavigate } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { AgentActions } from "@/components/AgentMenu/AgentActions";
import { useModals } from "@/providers/ModalsProvider";
import { useChatContext } from "@/providers/ChatProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

export function ActionsCard() {
  const navigate = useNavigate();
  const {
    name: agentName,
    agent,
    isBusy,
    start,
    stop,
    restart,
    rebuild,
    backup,
  } = useSelectedAgent();
  const { handleOpenAuth, setDeleteDialogOpen } = useModals();
  const { showToolCalls, setShowToolCalls } = useChatContext();

  const isRunning =
    agent?.status !== "stopped" &&
    agent?.status !== "dead" &&
    agent?.status !== "not_found";
  const showAuthenticate = agent?.status === "not_authenticated";
  const showAliveActions = agent?.status === "alive";

  return (
    <Card size="sm" className="lg:sticky lg:top-6">
      <CardContent>
        <AgentActions
          isRunning={isRunning}
          showAliveActions={showAliveActions}
          isBusy={isBusy}
          showToolCalls={showToolCalls}
          onLogs={() =>
            navigate(`/agent/${encodeURIComponent(agentName)}/logs`)
          }
          onToolCalls={() => setShowToolCalls((value) => !value)}
          onToggle={() => void (isRunning ? stop() : start())}
          onRestart={() => void restart()}
          onRebuild={() => void rebuild()}
          onBackup={() => void backup()}
          onAuthenticate={
            showAuthenticate ? () => void handleOpenAuth() : undefined
          }
          onDelete={() => setDeleteDialogOpen(true)}
        />
      </CardContent>
    </Card>
  );
}
