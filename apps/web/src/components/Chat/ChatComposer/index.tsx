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

interface VoiceButtonHandlers {
  onClick?: () => void;
  onPointerDown?: (e: PointerEvent<HTMLButtonElement>) => void;
  onPointerUp?: () => void;
  onKeyDown?: (e: KeyboardEvent<HTMLButtonElement>) => void;
  onKeyUp?: (e: KeyboardEvent<HTMLButtonElement>) => void;
  onBlur?: () => void;
}

function holdVoiceHandlers(toggleVoice: () => void): VoiceButtonHandlers {
  return {
    onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
      e.preventDefault();
      e.currentTarget.setPointerCapture(e.pointerId);
      if (!useVoice.getState().isRecording) toggleVoice();
    },
    onPointerUp: () => {
      if (useVoice.getState().isRecording) toggleVoice();
    },
    onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => {
      if (e.repeat || (e.key !== " " && e.key !== "Enter")) return;
      e.preventDefault();
      if (!useVoice.getState().isRecording) toggleVoice();
    },
    onKeyUp: (e: KeyboardEvent<HTMLButtonElement>) => {
      if (e.key !== " " && e.key !== "Enter") return;
      if (useVoice.getState().isRecording) toggleVoice();
    },
    onBlur: () => {
      if (useVoice.getState().isRecording) toggleVoice();
    },
  };
}

function placeholderText(isRecording: boolean, notAuthenticated: boolean) {
  if (isRecording) return "listening...";
  return notAuthenticated ? "sign in to chat" : "send a message...";
}

function composerPadding(fullscreen: boolean | undefined, isMobile: boolean) {
  if (!fullscreen) return "px-2.5 pb-2.5";
  return cn(
    "px-[calc(var(--page-padding-x)/2)]",
    isMobile ? "pb-1" : "pb-[calc(var(--page-padding-x)/2)]",
  );
}

interface ChatComposerProps {
  fullscreen?: boolean;
  connected: boolean;
  notAuthenticated: boolean;
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
  notAuthenticated,
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

  const voiceButtonHandlers: VoiceButtonHandlers =
    activation === "hold"
      ? holdVoiceHandlers(toggleVoice)
      : { onClick: toggleVoice };

  const showSend = !isRecording || !voiceAutoSend;
  const useLiveTranscript =
    isRecording && (voiceAutoSend || activation === "hold");
  const inputDisabled = !connected || notAuthenticated;

  return (
    <div
      className={cn(
        "flex items-end gap-2",
        composerPadding(fullscreen, isMobile),
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
          placeholder={placeholderText(isRecording, notAuthenticated)}
          disabled={inputDisabled}
          rows={1}
          enterKeyHint="send"
          className="max-h-[240px] md:text-base"
        />
        {showSend && (
          <InputGroupAddon align="inline-end" className="gap-0 py-0.5 pr-0.5">
            <InputGroupButton
              size="icon-sm"
              variant="ghost"
              aria-label="send message"
              disabled={inputDisabled}
              onClick={onSend}
              className="size-11 [&_svg]:size-4"
            >
              <SendHorizontal />
            </InputGroupButton>
          </InputGroupAddon>
        )}
      </InputGroup>
      <VoiceButtons
        sttAvailable={sttAvailable}
        isSpeaking={isSpeaking}
        isRecording={isRecording}
        inputDisabled={inputDisabled}
        handlers={voiceButtonHandlers}
        onStopSpeech={onStopSpeech}
      />
    </div>
  );
}

function VoiceButtons({
  sttAvailable,
  isSpeaking,
  isRecording,
  inputDisabled,
  handlers,
  onStopSpeech,
}: {
  sttAvailable: boolean;
  isSpeaking: boolean;
  isRecording: boolean;
  inputDisabled: boolean;
  handlers: VoiceButtonHandlers;
  onStopSpeech: () => void;
}) {
  if (!sttAvailable && !isSpeaking) return null;

  return (
    <div className="relative shrink-0">
      {sttAvailable && (
        <Button
          type="button"
          size="icon"
          variant="secondary"
          disabled={inputDisabled}
          aria-label={isRecording ? "Stop recording" : "Start recording"}
          {...handlers}
          className={cn(
            "size-12 touch-none rounded-full [&_svg]:size-5",
            isRecording && "bg-red-500 text-white hover:bg-red-600",
          )}
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
  );
}
