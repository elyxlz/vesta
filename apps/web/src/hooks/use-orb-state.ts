import {
  getAgentVisualStatus,
  type OrbVisualState,
} from "@/components/Orb/styles";
import type { AgentActivityState, ModelAccess } from "@vesta/core";
import { useAgentOps } from "@/stores/use-agent-ops";

interface AgentLike {
  name: string;
  status: string;
  modelAccess?: ModelAccess;
}

export function useOrbStatus(
  agent: AgentLike | null,
  activityState: AgentActivityState,
): { orbState: OrbVisualState; label: string } {
  const operation = useAgentOps((s) =>
    agent ? s.getOp(agent.name).operation : "idle",
  );
  const { orbState, label } = getAgentVisualStatus(
    agent,
    operation,
    "",
    activityState,
  );
  return { orbState, label };
}

export function useOrbState(
  agent: AgentLike | null,
  activityState: AgentActivityState,
): OrbVisualState {
  return useOrbStatus(agent, activityState).orbState;
}
