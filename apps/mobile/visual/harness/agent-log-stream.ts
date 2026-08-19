import type { SseHandle, StreamEvent } from "@vesta/core";
import type { ApiClient } from "../../src/api/client";
import { visualSwitch } from "./launch-query";

// visualLogs=empty streams nothing (the waiting state); visualLogs=error
// reports a failed stream after the first lines, and the reconnect holds its
// first line back long enough that the error header stays up for the shot
// (the next line is what clears it).
const logsVariant = visualSwitch("visualLogs");
const RECONNECT_HOLD_MS = 60_000;

// A realistic boot tail: enough lines to overflow the viewport, streamed one per tick the way
// readSse delivers a replay, so the list's fill-on-burst behavior is exercised. The newest line
// ("gateway sync ready") arrives last, which puts it at the inverted list's visual bottom where
// the flow asserts it.
const LEVELS = [
  "\u001b[32mINFO\u001b[0m",
  "\u001b[36mINFO\u001b[0m",
  "\u001b[33mNOTICE\u001b[0m",
  "\u001b[35mDEBUG\u001b[0m",
];
const BOOT_TAIL_LENGTH = 45;

const bootTail = Array.from({ length: BOOT_TAIL_LENGTH }, (_, index) => {
  const level = LEVELS[index % LEVELS.length] ?? LEVELS[0];
  return `${level} boot step ${String(index + 1).padStart(2, "0")} settled`;
});

const lines = [
  ...bootTail,
  "\u001b[36mINFO\u001b[0m loaded 4 visual QA scenarios",
  "\u001b[33mNOTICE\u001b[0m reviewing onboarding polish",
  "\u001b[32mINFO\u001b[0m notification routing healthy",
  "\u001b[35mDEBUG\u001b[0m next check scheduled in 5 minutes",
  "\u001b[32mINFO\u001b[0m gateway sync ready",
];

export function openAgentLogStream(
  _api: ApiClient,
  _name: string,
  reconnect: boolean,
  onEvent: (event: StreamEvent) => void,
): SseHandle {
  const streamed = logsVariant === "empty" ? [] : lines;
  const hold = logsVariant === "error" && reconnect ? RECONNECT_HOLD_MS : 0;
  const timers = streamed.map((text, index) =>
    setTimeout(() => onEvent({ kind: "line", text }), hold + index * 12),
  );
  if (logsVariant === "error" && !reconnect) {
    timers.push(
      setTimeout(
        () => onEvent({ kind: "error", message: "error: stream closed" }),
        streamed.length * 12 + 20,
      ),
    );
  }
  return {
    cancel: () => {
      for (const timer of timers) clearTimeout(timer);
    },
  };
}
