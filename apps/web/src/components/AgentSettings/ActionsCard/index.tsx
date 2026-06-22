import { useNavigate } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
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
  const showAliveActions = agent?.status === "alive";
  const isAuthenticated = Boolean(
    agent && agent.status !== "not_authenticated",
  );

  // An agent that needs auth is an urgent action: lift "sign in" to a primary
  // button at the top and drop the routine auth row from the list below (the
  // list keeps "switch provider" once authed).
  const needsAuth = !isAuthenticated;

  return (
    <Card size="sm">
      <CardContent>
        {needsAuth && (
          <Button
            variant="default"
            size="lg"
            className="mb-4 w-full"
            onClick={() => void handleOpenAuth()}
          >
            <KeyRound data-icon="inline-start" />
            sign in
          </Button>
        )}
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
            isAuthenticated ? () => void handleOpenAuth() : undefined
          }
          isAuthenticated={isAuthenticated}
          onDelete={() => setDeleteDialogOpen(true)}
        />
      </CardContent>
    </Card>
  );
}
