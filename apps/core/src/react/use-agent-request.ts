import { useSyncExternalStore } from "react";
import {
  agentVisualStatus,
  IDLE_REQUEST,
  type AgentRequest,
  type AgentRequestState,
  type AgentVisualSource,
} from "../agent-request/agent-request";
import type { AgentActivityState } from "../protocol/tree";
import type { Controller } from "../controller/controller";
import type { OrbVisualState } from "../agent-status/agent-status";

const subscribeNothing = (): (() => void) => () => undefined;
const idle = (): AgentRequestState => IDLE_REQUEST;

// This client's own in-flight request for `name`, as the controller holds it; idle with no
// controller or no agent.
export function useAgentRequest(
  controller: Controller | null,
  name: string | null,
): AgentRequestState {
  const requests = controller?.requests ?? null;
  const read =
    requests && name !== null
      ? (): AgentRequestState => requests.get(name)
      : idle;
  return useSyncExternalStore(
    requests?.subscribe ?? subscribeNothing,
    read,
    read,
  );
}

interface AgentVisualStatusView {
  label: string;
  orbState: OrbVisualState;
  request: AgentRequest;
  // The last failure of this client's own request, or "". Callers that show it put it in place
  // of the label.
  error: string;
}

// The words and orb state for an agent as this client should render them: its own request first,
// then the roster.
export function useAgentVisualStatus(
  controller: Controller | null,
  agent: (AgentVisualSource & { name: string }) | null,
  activityState: AgentActivityState,
): AgentVisualStatusView {
  const state = useAgentRequest(controller, agent?.name ?? null);
  const { label, orbState } = agentVisualStatus(
    agent,
    state.request,
    activityState,
  );
  return { label, orbState, request: state.request, error: state.error };
}
