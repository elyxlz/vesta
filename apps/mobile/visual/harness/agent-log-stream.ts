import type { SseHandle, StreamEvent } from "@vesta/core";
import type { ApiClient } from "../../src/api/client";

const lines = [
  "\u001b[32mINFO\u001b[0m gateway sync ready",
  "\u001b[36mINFO\u001b[0m loaded 4 visual QA scenarios",
  "\u001b[33mNOTICE\u001b[0m reviewing onboarding polish",
  "\u001b[32mINFO\u001b[0m notification routing healthy",
  "\u001b[35mDEBUG\u001b[0m next check scheduled in 5 minutes",
];

export function openAgentLogStream(
  _api: ApiClient,
  _name: string,
  _reconnect: boolean,
  onEvent: (event: StreamEvent) => void,
): SseHandle {
  const timers = lines.map((text, index) =>
    setTimeout(() => onEvent({ kind: "line", text }), index * 12),
  );
  return {
    cancel: () => {
      for (const timer of timers) clearTimeout(timer);
    },
  };
}
