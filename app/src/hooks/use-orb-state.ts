import {
  getOrbVisualState,
  type OrbVisualState,
} from "@/components/Orb/styles";
import type { AgentActivityState } from "@/lib/types";
import { useAgentOps } from "@/stores/use-agent-ops";

interface AgentLike {
  name: string;
  status: string;
  authenticated: boolean;
  agent_ready: boolean;
}

export function useOrbState(
  agent: AgentLike | null,
  activityState: AgentActivityState,
): OrbVisualState {
  const operation = useAgentOps((s) =>
    agent ? s.getOp(agent.name).operation : "idle",
  );
  if (!agent) return "dead";
  return getOrbVisualState(
    agent.status,
    agent.authenticated,
    agent.agent_ready,
    activityState,
    operation,
  );
}
