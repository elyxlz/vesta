import type { AgentRequest } from "@vesta/core";

export type AgentAction = "start" | "stop" | "restart" | "backup" | "delete";

// The request this client holds on the agent from the tap until the gateway answers, the same
// words web shows for the same button. A restart reads as starting: the stop half is what the
// roster reports, and the start is what the user asked for.
export function agentActionRequest(
  action: AgentAction,
): Exclude<AgentRequest, "idle"> {
  switch (action) {
    case "start":
    case "restart":
      return "starting";
    case "stop":
      return "stopping";
    case "backup":
      return "backing-up";
    case "delete":
      return "deleting";
  }
}
