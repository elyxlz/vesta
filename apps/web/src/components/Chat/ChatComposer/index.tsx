import { micHandlers } from "./mic-handlers";
import type {
  ChangeEvent,
  ClipboardEvent,
  KeyboardEvent,
  RefObject,
} from "react";
import { cn } from "@/lib/utils";
import type { VoiceMode } from "@/stores/use-voice";
import { usePreferences } from "@/stores/use-preferences";
import { useIsMobile } from "@/hooks/use-mobile";
import type { AttachmentDrafts } from "@/stores/use-attachment-drafts";
import { rightSlot } from "./right-slot";
import { FloatingComposer, type ComposerControls } from "./floating-composer";

function placeholderText({
  recordingMode,
  listening,
  notAuthenticated,
  agentName,
  hasAttachments,
}: {
  recordingMode: VoiceMode | null;
  listening: boolean;
  notAuthenticated: boolean;
  agentName: string;
  hasAttachments: boolean;
}) {
  if (recordingMode === "dictation") {
    return listening ? "listening..." : "connecting...";
  }
  if (notAuthenticated) return "sign in to chat";
  if (hasAttachments) return "add a caption";
  return `message ${agentName}`.toLowerCase();
}

function composerPadding(fullscreen: boolean | undefined, isMobile: boolean) {
  // px-4 lines the desktop composer up with the bubbles' column. Bottom gap:
  // 16px on desktop fullscreen, 12px on the split panel, 4px on mobile where
  // the composer sits low over the card.
  if (!isMobile) return fullscreen ? "px-4 pb-4" : "px-4 pb-3";
  return cn(
    fullscreen ? "px-[calc(var(--page-padding-x)/2)]" : "px-2.5",
    "pb-1",
  );
}

interface ChatComposerProps {
  fullscreen?: boolean;
  agentName: string;
  notAuthenticated: boolean;
  voiceConfigured: boolean;
  recordingMode: VoiceMode | null;
  listening: boolean;
  liveTranscript: string;
  // The parent freezes its measurement-driven layout when the conversation flips; this settle
  // report is what releases the freeze once the pill's animation lands.
  onMorphSettled?: () => void;
  onHeightAnimation?: (animating: boolean) => void;
  startVoice: (mode: VoiceMode) => void;
  stopVoice: () => void;
  cancelVoice: () => void;
  input: string;
  onInputChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: KeyboardEvent) => void;
  onPaste: (e: ClipboardEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
  canSend: boolean;
  attachments: AttachmentDrafts;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}

export function ChatComposer({
  fullscreen,
  agentName,
  notAuthenticated,
  voiceConfigured,
  recordingMode,
  listening,
  liveTranscript,
  onMorphSettled,
  onHeightAnimation,
  startVoice,
  stopVoice,
  cancelVoice,
  input,
  onInputChange,
  onKeyDown,
  onPaste,
  onSend,
  canSend,
  attachments,
  textareaRef,
}: ChatComposerProps) {
  const isMobile = useIsMobile();
  const activation = usePreferences((s) => s.voiceActivation);
  // The input shows what dictation has captured so far; a conversation lives in its drawer.
  const useLiveTranscript = recordingMode === "dictation";
  // Only sign-in disables the field; a dropped connection still lets you type (a send while
  // disconnected is blocked with a toast in the parent instead).
  const inputDisabled = notAuthenticated;
  const value = useLiveTranscript ? liveTranscript : input;
  const hasAttachments = attachments.drafts.length > 0;
  const placeholder = placeholderText({
    recordingMode,
    listening,
    notAuthenticated,
    agentName,
    hasAttachments,
  });
  const controls: ComposerControls = {
    voiceConfigured,
    recordingMode,
    inputDisabled,
    slot: rightSlot({ input, recordingMode, hasAttachments }),
    micHandlers: micHandlers(activation, startVoice, stopVoice),
    onConfirm: stopVoice,
    onCancel: cancelVoice,
    onConversation: () => {
      if (recordingMode === "conversation") stopVoice();
      else startVoice("conversation");
    },
    onSend,
    canSend,
  };

  return (
    <FloatingComposer
      paddingClass={composerPadding(fullscreen, isMobile)}
      value={value}
      placeholder={placeholder}
      readOnly={useLiveTranscript}
      onInputChange={onInputChange}
      onKeyDown={onKeyDown}
      onPaste={onPaste}
      textareaRef={textareaRef}
      controls={controls}
      attachments={attachments}
      onMorphSettled={onMorphSettled}
      onHeightAnimation={onHeightAnimation}
    />
  );
}
