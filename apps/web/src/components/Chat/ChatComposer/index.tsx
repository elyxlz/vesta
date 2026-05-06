import type {
  ChangeEvent,
  KeyboardEvent,
  PointerEvent,
  RefObject,
} from "react";
import { AnimatePresence, motion } from "motion/react";
import { Mic, SendHorizontal, Square, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import { cn } from "@/lib/utils";
import { useVoice } from "@/stores/use-voice";
import { useVoiceActivation } from "@/stores/use-voice-activation";
import { useIsMobile } from "@/hooks/use-mobile";

interface ChatComposerProps {
  fullscreen?: boolean;
  connected: boolean;
  sttAvailable: boolean;
  isRecording: boolean;
  voiceAutoSend: boolean;
  liveTranscript: string;
  toggleVoice: () => void;
  isSpeaking: boolean;
  onStopSpeech: () => void;
  input: string;
  onInputChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: KeyboardEvent) => void;
  onSend: () => void;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}

export function ChatComposer({
  fullscreen,
  connected,
  sttAvailable,
  isRecording,
  voiceAutoSend,
  liveTranscript,
  toggleVoice,
  isSpeaking,
  onStopSpeech,
  input,
  onInputChange,
  onKeyDown,
  onSend,
  textareaRef,
}: ChatComposerProps) {
  const activation = useVoiceActivation((s) => s.mode);
  const isMobile = useIsMobile();

  const voiceButtonHandlers =
    activation === "hold"
      ? {
          onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
            e.preventDefault();
            if (!useVoice.getState().isRecording) toggleVoice();
          },
          onPointerUp: () => {
            if (useVoice.getState().isRecording) toggleVoice();
          },
          onPointerLeave: () => {
            if (useVoice.getState().isRecording) toggleVoice();
          },
        }
      : { onClick: toggleVoice };

  const showSend = !isRecording || !voiceAutoSend;
  const useLiveTranscript =
    isRecording && (voiceAutoSend || activation === "hold");

  return (
    <div
      className={cn(
        "flex items-end gap-2",
        fullscreen && "px-[calc(var(--page-padding-x)/2)]",
        fullscreen && !isMobile && "pb-[calc(var(--page-padding-x)/2)]",
        fullscreen && isMobile && "pb-1",
        !fullscreen && "px-2.5 pb-2.5",
      )}
    >
      <InputGroup
        className={cn(
          "min-h-12 px-1 flex-1",
          fullscreen && isMobile
            ? "bg-card shadow-md ring-1 ring-foreground/5 dark:ring-foreground/10"
            : "bg-secondary",
          isRecording &&
            "ring-2 ring-red-500 has-[[data-slot=input-group-control]:focus-visible]:border-transparent has-[[data-slot=input-group-control]:focus-visible]:ring-2 has-[[data-slot=input-group-control]:focus-visible]:ring-red-500",
        )}
      >
        <InputGroupTextarea
          ref={textareaRef}
          value={useLiveTranscript ? liveTranscript : input}
          onChange={onInputChange}
          onKeyDown={onKeyDown}
          readOnly={useLiveTranscript}
          placeholder={isRecording ? "listening..." : "send a message..."}
          disabled={!connected}
          rows={1}
          enterKeyHint="send"
          className="max-h-[120px] md:text-base"
        />
        {showSend && (
          <InputGroupAddon align="inline-end" className="gap-0">
            <InputGroupButton
              size="icon-sm"
              variant="ghost"
              disabled={!connected}
              onClick={onSend}
            >
              <SendHorizontal />
            </InputGroupButton>
          </InputGroupAddon>
        )}
      </InputGroup>
      {(sttAvailable || isSpeaking) && (
        <div className="relative shrink-0">
          {sttAvailable && (
            <Button
              type="button"
              size="icon"
              disabled={!connected}
              aria-label={isRecording ? "Stop recording" : "Start recording"}
              {...voiceButtonHandlers}
              className="size-12 rounded-full bg-red-500 text-white hover:bg-red-600 [&_svg]:size-5"
            >
              {isRecording ? <Square fill="currentColor" /> : <Mic />}
            </Button>
          )}
          <AnimatePresence>
            {isSpeaking && (
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 16 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
                className={cn(sttAvailable && "absolute -top-14 left-0")}
              >
                <Button
                  type="button"
                  size="icon"
                  variant="secondary"
                  onClick={onStopSpeech}
                  aria-label="Stop voice playback"
                  title="Stop voice playback"
                  className="size-12 rounded-full [&_svg]:size-5"
                >
                  <VolumeX />
                </Button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
