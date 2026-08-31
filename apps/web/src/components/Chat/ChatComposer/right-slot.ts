import type { VoiceMode } from "@/stores/use-voice";

export type RightSlot = "conversation" | "send";

// The slot next to the mic: a conversation starter while there is nothing to send, send once a
// draft exists (typed text or attachment chips), and held on conversation while one runs so the
// button never flips under a tap.
export function rightSlot({
  input,
  recordingMode,
  hasAttachments,
}: {
  input: string;
  recordingMode: VoiceMode | null;
  hasAttachments: boolean;
}): RightSlot {
  if (recordingMode === "conversation") return "conversation";
  return input.trim().length === 0 && !hasAttachments ? "conversation" : "send";
}
