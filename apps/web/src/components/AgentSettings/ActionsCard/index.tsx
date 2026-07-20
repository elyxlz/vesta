import { useNavigate } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AgentActions } from "@/components/AgentMenu/AgentActions";
import { useIsMobile } from "@/hooks/use-mobile";
import { useGateway } from "@/providers/GatewayProvider";
import { useModals } from "@/providers/ModalsProvider";
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
    backup,
  } = useSelectedAgent();
  const { handleOpenAuth, setDeleteDialogOpen } = useModals();

  const isRunning =
    agent.status !== "stopped" &&
    agent.status !== "dead" &&
    agent.status !== "not_found";
  const showAliveActions = agent.status === "alive";
  const isAuthenticated =
    agent.status !== "not_authenticated" && agent.status !== "unprovisioned";

  // On mobile (no navbar sign-in button) an agent that needs auth is an urgent
  // action: lift "sign in" to a primary button at the top and drop the routine
  // auth row from the list below. Desktop keeps it as a normal list row. Auth is
  // only offered when the gateway is reachable — signing in is moot while offline.
  const isMobile = useIsMobile();
  const { reachable } = useGateway();
  const showTopSignIn = isMobile && !isAuthenticated && reachable;

  return (
    <Card size="sm">
      <CardContent>
        {showTopSignIn && (
          <Button
            variant="default"
            size="lg"
            className="mb-4 w-full"
            onClick={() => handleOpenAuth()}
          >
            <KeyRound data-icon="inline-start" />
            sign in
          </Button>
        )}
        <AgentActions
          isRunning={isRunning}
          showAliveActions={showAliveActions}
          isBusy={isBusy}
          onLogs={() => {
            void navigate(`/agent/${encodeURIComponent(agentName)}/logs`);
          }}
          onToggle={() => {
            if (isRunning) stop();
            else start();
          }}
          onRestart={() => void restart()}
          onBackup={() => backup()}
          onDelete={() => setDeleteDialogOpen(true)}
        />
      </CardContent>
    </Card>
  );
}
