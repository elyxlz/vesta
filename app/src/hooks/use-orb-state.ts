import {
  getAgentVisualStatus,
  type OrbVisualState,
} from "@/components/Orb/styles";
import type { AgentActivityState } from "@/lib/types";
import { useAgentOps } from "@/stores/use-agent-ops";

interface AgentLike {
  name: string;
  alive: boolean;
  status: string;
  authenticated: boolean;
  agent_ready: boolean;
  friendly_status: string;
}

export function useOrbState(
  agent: AgentLike | null,
  activityState: AgentActivityState,
): OrbVisualState {
  const operation = useAgentOps((s) =>
    agent ? s.getOp(agent.name).operation : "idle",
  );
  return getAgentVisualStatus(agent, operation, "", activityState).orbState;
}
