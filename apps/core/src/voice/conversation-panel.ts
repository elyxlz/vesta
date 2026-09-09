// What the conversation panel says between turns, in priority order: a session still dialing,
// the agent talking, a muted mic, the agent thinking, else listening.
export type ConversationPhase =
  "connecting" | "speaking" | "muted" | "thinking" | "listening";

export function conversationPhase(input: {
  listening: boolean;
  micMuted: boolean;
  speaking: boolean;
  thinking: boolean;
}): ConversationPhase {
  if (!input.listening) return "connecting";
  if (input.speaking) return "speaking";
  if (input.micMuted) return "muted";
  if (input.thinking) return "thinking";
  return "listening";
}

// The live transcript split so the freshest word can be set bold: everything up to and
// including the last space, then the last word.
export function splitSpokenTail(transcript: string): {
  head: string;
  tail: string;
} {
  const lastSpace = transcript.lastIndexOf(" ");
  if (lastSpace === -1) return { head: "", tail: transcript };
  return {
    head: transcript.slice(0, lastSpace + 1),
    tail: transcript.slice(lastSpace + 1),
  };
}
