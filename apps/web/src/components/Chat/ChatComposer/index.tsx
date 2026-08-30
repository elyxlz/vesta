import {
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
} from "react";
import { AnimatePresence, motion } from "motion/react";
import { Mic, SendHorizontal, Square, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useVoice } from "@/stores/use-voice";
import { useVoiceActivation } from "@/stores/use-voice-activation";
import { useIsMobile } from "@/hooks/use-mobile";
import type { AttachmentDrafts } from "@/stores/use-attachment-drafts";
import { AttachmentChips } from "../AttachmentChips";
import { AttachMenu } from "./AttachMenu";

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

// Snappy, low-bounce spring for the composer's collapse/expand layout animation.
const LAYOUT_TRANSITION = {
  type: "spring",
  stiffness: 650,
  damping: 50,
} as const;

function placeholderText(
  isRecording: boolean,
  notAuthenticated: boolean,
  agentName: string,
  hasAttachments: boolean,
) {
  if (isRecording) return "listening...";
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
  onPaste,
  onSend,
  canSend,
  attachments,
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
  // Only sign-in disables the field; a dropped connection still lets you type (a send while
  // disconnected is blocked with a toast in the parent instead).
  const inputDisabled = notAuthenticated;
  const value = useLiveTranscript ? liveTranscript : input;
  const placeholder = placeholderText(
    isRecording,
    notAuthenticated,
    agentName,
    attachments.drafts.length > 0,
  );
  const controls = {
    sttAvailable,
    isSpeaking,
    isRecording,
    inputDisabled,
    voiceButtonHandlers,
    onStopSpeech,
    showSend,
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
    />
  );
}

interface ComposerControls {
  sttAvailable: boolean;
  isSpeaking: boolean;
  isRecording: boolean;
  inputDisabled: boolean;
  voiceButtonHandlers: VoiceButtonHandlers;
  onStopSpeech: () => void;
  showSend: boolean;
  onSend: () => void;
  canSend: boolean;
}

function FloatingComposer({
  paddingClass,
  value,
  placeholder,
  readOnly,
  onInputChange,
  onKeyDown,
  onPaste,
  textareaRef,
  controls,
  attachments,
}: {
  paddingClass: string;
  value: string;
  placeholder: string;
  readOnly: boolean;
  onInputChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: KeyboardEvent) => void;
  onPaste: (e: ClipboardEvent<HTMLTextAreaElement>) => void;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  controls: ComposerControls;
  attachments: AttachmentDrafts;
}) {
  const {
    sttAvailable,
    isSpeaking,
    isRecording,
    inputDisabled,
    voiceButtonHandlers,
    onStopSpeech,
    showSend,
    onSend,
    canSend,
  } = controls;

  // Expand (input onto its own full-width row above the buttons) once the text would wrap
  // past one line in the collapsed inline width. A hidden single-line mirror measured against
  // the cached collapsed input width keeps the decision stable, so it can't oscillate.
  const measureRef = useRef<HTMLSpanElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const collapsedWidthRef = useRef(0);
  const [expanded, setExpanded] = useState(false);
  // Radius = half the collapsed height, so it's a true pill when collapsed and holds those same
  // corners as a rounded rectangle once it grows. Measured while collapsed and kept fixed.
  const [pillRadius, setPillRadius] = useState(24);
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!expanded && el) {
      // Content width (client box minus the textarea's own horizontal padding) is what the
      // text actually wraps against; caching it while collapsed keeps the decision stable.
      const style = getComputedStyle(el);
      const padX =
        parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      collapsedWidthRef.current = el.clientWidth - padX;
    }
    if (!expanded && containerRef.current) {
      setPillRadius(containerRef.current.offsetHeight / 2);
    }
  }, [expanded, textareaRef]);
  useLayoutEffect(() => {
    const span = measureRef.current;
    if (!span) return;
    const avail = collapsedWidthRef.current;
    const width = span.scrollWidth;
    setExpanded((prev) => {
      if (value.trim().length === 0) return false;
      if (value.includes("\n")) return true;
      if (avail <= 0) return prev;
      // Expand a hair before the last word would wrap so the narrow field never shows two
      // lines first; once expanded, hold until the text clearly fits again (hysteresis).
      return prev ? width > avail - 24 : width > avail - 8;
    });
  }, [value]);

  return (
    <div className={paddingClass}>
      <motion.div
        ref={containerRef}
        layout
        transition={LAYOUT_TRANSITION}
        // Radius in style (not className) so motion counter-scales it during the layout
        // animation instead of warping the corners.
        style={{ borderRadius: pillRadius }}
        className={cn(
          "flex flex-wrap items-end gap-1 border border-border bg-popover px-2 pb-1.5 shadow-sm",
          // Sides + bottom stay fixed so the bottom-row buttons don't move; only the top grows
          // to give the input its own breathing room once it moves onto its own row.
          expanded ? "pt-3" : "pt-1.5",
          "has-[textarea:focus-visible]:ring-2 has-[textarea:focus-visible]:ring-ring/30",
          isRecording && "ring-2 ring-red-500",
        )}
      >
        {/* Off-screen single-line mirror of the text, to detect the wrap point. */}
        <span
          ref={measureRef}
          aria-hidden
          className="pointer-events-none invisible fixed top-0 left-[-9999px] whitespace-pre md:text-base"
        >
          {value || " "}
        </span>

        <AttachmentChips
          drafts={attachments.drafts}
          previewUrl={attachments.previewUrl}
          onRetry={attachments.retry}
          onRemove={attachments.remove}
        />

        <motion.div
          layout
          transition={LAYOUT_TRANSITION}
          className={cn("shrink-0", expanded ? "order-2" : "order-1")}
        >
          <AttachMenu disabled={inputDisabled} onFiles={attachments.addFiles} />
        </motion.div>

        <motion.div
          layout
          transition={LAYOUT_TRANSITION}
          className={cn(
            "flex min-w-0 items-center self-stretch",
            expanded ? "order-1 basis-full" : "order-2 flex-1",
          )}
        >
          <textarea
            ref={textareaRef}
            value={value}
            onChange={onInputChange}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            readOnly={readOnly}
            placeholder={placeholder}
            disabled={inputDisabled}
            rows={1}
            enterKeyHint="send"
            className="field-sizing-content max-h-[240px] w-full resize-none bg-transparent px-1 py-1.5 leading-6 outline-none placeholder:text-muted-foreground disabled:opacity-50 md:text-base"
          />
        </motion.div>

        <motion.div
          layout
          transition={LAYOUT_TRANSITION}
          className={cn(
            "flex shrink-0 items-end gap-1 order-3",
            expanded && "ml-auto",
          )}
        >
          <VoiceButtons
            sttAvailable={sttAvailable}
            isSpeaking={isSpeaking}
            isRecording={isRecording}
            inputDisabled={inputDisabled}
            handlers={voiceButtonHandlers}
            onStopSpeech={onStopSpeech}
          />
          {showSend && (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label="send message"
              disabled={inputDisabled || !canSend}
              onClick={onSend}
              className="size-9 rounded-full [&_svg]:size-4"
            >
              <SendHorizontal />
            </Button>
          )}
        </motion.div>
      </motion.div>
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

  const sizeClass = "size-9 [&_svg]:size-4";

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
            "touch-none rounded-full",
            sizeClass,
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
            className={cn(sttAvailable && "absolute left-0 -top-11")}
          >
            <Button
              type="button"
              size="icon"
              variant="secondary"
              onClick={onStopSpeech}
              aria-label="Stop voice playback"
              title="Stop voice playback"
              className={cn("rounded-full", sizeClass)}
            >
              <VolumeX />
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
