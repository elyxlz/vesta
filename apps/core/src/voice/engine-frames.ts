// The frames of the voice engine socket that a client reads, parsed at the boundary. A frame
// type or a field that this parser does not know reads as null: the engine can add both, and a
// client ignores them by rule. agent/skills/voice/PROTOCOL.md is the reference.

import { record } from "../protocol/parse";

export type EngineFrame =
  // The engine sends a state on each change; the first one says that it accepted the session.
  | { type: "state" }
  | { type: "transcript"; text: string }
  | { type: "turn_start" }
  | { type: "turn_end"; text: string }
  | { type: "turn_dropped" }
  | { type: "play"; id: string; url: string }
  | { type: "pause_playback" }
  | { type: "resume_playback" }
  | { type: "stop_playback" }
  // With the wake word on: true while the engine waits for the phrase, false while it listens.
  | { type: "wake_listening"; value: boolean }
  // `id` names the reply that cannot play; null for an error of the session.
  | { type: "error"; id: string | null; message: string }
  | { type: "ended"; reason: string };

function parsed(data: string): Record<string, unknown> | null {
  try {
    return record(JSON.parse(data));
  } catch {
    return null;
  }
}

export function parseEngineFrame(data: string): EngineFrame | null {
  const body = parsed(data);
  if (!body) return null;
  const { type, text, id, url, reason, message, value } = body;
  switch (type) {
    case "state":
    case "turn_start":
    case "turn_dropped":
    case "pause_playback":
    case "resume_playback":
    case "stop_playback":
      return { type };
    case "transcript":
    case "turn_end":
      return typeof text === "string" ? { type, text } : null;
    case "play":
      // A play with no url belongs to `bytes` delivery, which this client never asks for.
      return typeof id === "string" && typeof url === "string"
        ? { type, id, url }
        : null;
    case "wake_listening":
      return typeof value === "boolean" ? { type, value } : null;
    case "error":
      return typeof message === "string"
        ? { type, id: typeof id === "string" ? id : null, message }
        : null;
    case "ended":
      return { type, reason: typeof reason === "string" ? reason : "" };
    default:
      return null;
  }
}
