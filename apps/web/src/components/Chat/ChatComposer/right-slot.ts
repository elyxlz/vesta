import type { VoiceMode } from "@/stores/use-voice";

export type RightSlot = "conversation" | "send";

// The slot next to the mic: a conversation starter while there is nothing to send, send once a
// draft exists, and held on conversation while one runs so the button never flips under a tap.
export function rightSlot({
  input,
  recordingMode,
}: {
  input: string;
  recordingMode: VoiceMode | null;
}): RightSlot {
  if (recordingMode === "conversation") return "conversation";
  return input.trim().length === 0 ? "conversation" : "send";
}
