import type { LogEvent } from "./types";

// The single owner of how a log-stream event maps to a viewer action. Kept pure
// and separate from the Console component so the reconnect policy is unit-testable:
// crucially, a clean "agent_stopped" (End) is terminal and must NOT trigger a
// reconnect (otherwise a stopped agent re-replays its log tail on a tight loop),
// while a genuine transport Error must reconnect.
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
