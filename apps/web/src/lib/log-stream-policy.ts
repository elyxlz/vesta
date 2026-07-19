import type { AgentStatus } from "@vesta/core";
import type { LogEvent } from "./types";

// The single owner of how the log viewer reacts to the stream and to agent
// liveness. Kept pure and separate from the Console component so the policy is
// unit-testable: crucially, a clean "agent_stopped" (End) is terminal and must
// NOT trigger a reconnect (otherwise a stopped agent re-replays its log tail on a
// tight loop), while a genuine transport Error must reconnect.
export type LogStreamAction =
  | { kind: "append"; text: string }
  | { kind: "stopped" }
  | { kind: "reconnect" };

export function logStreamAction(event: LogEvent): LogStreamAction {
  switch (event.kind) {
    case "Line":
      return { kind: "append", text: event.text };
    case "End":
      return { kind: "stopped" };
    case "Error":
      return { kind: "reconnect" };
  }
}

// The statuses where the agent's container is not running, so the log endpoint
// returns the final tail + agent_stopped rather than a live `tail -f`.
const CONTAINER_DOWN_STATUSES: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "stopped",
  "dead",
  "not_found",
]);

// Whether the container is up and will stream live logs. Drives resume-on-restart
// off the authoritative status instead of polling a stopped agent.
export function isAgentContainerUp(status: AgentStatus): boolean {
  return !CONTAINER_DOWN_STATUSES.has(status);
}

// How far back the viewer can scroll: the lines a fresh stream asks the server to
// replay, and the lines the Console keeps before dropping the oldest. One number so
// the two agree; a request deeper than the buffer would drop lines on arrival, a
// buffer deeper than the request would reserve scrollback that never fills.
export const LOG_SCROLLBACK_LINES = 5000;

// The `tail` a stream requests: the full scrollback on a fresh connect, none on a
// reconnect after a transport drop, where the replayed block is already on screen
// and would re-append as duplicates.
export function replayTailLines(replay: boolean): number {
  return replay ? LOG_SCROLLBACK_LINES : 0;
}
