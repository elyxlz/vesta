import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
} from "react";
import {
  AudioLines,
  Check,
  Mic,
  SendHorizontal,
  Square,
  X,
} from "lucide-react";
import { AnimatePresence, motion as m } from "motion/react";
import { useMeasuredSize } from "@/hooks/use-measured-size";
import { Button } from "@/components/ui/button";
import {
  ConversationPanel,
  RECORDING_BUTTON,
} from "@/components/Chat/ConversationPanel";
import { cn } from "@/lib/utils";
import { useVoice, type VoiceMode } from "@/stores/use-voice";
import {
  useVoiceActivation,
  type VoiceActivationMode,
} from "@/stores/use-voice-activation";
import { useIsMobile } from "@/hooks/use-mobile";
import type { AttachmentDrafts } from "@/stores/use-attachment-drafts";
import { AttachmentChips } from "../AttachmentChips";
import { AttachMenu } from "./AttachMenu";
import { rightSlot } from "./right-slot";

interface MicHandlers {
  onClick?: () => void;
  onPointerDown?: (e: PointerEvent<HTMLButtonElement>) => void;
}

// Toggle: a click starts dictation and the confirm button sends it. Hold: pressing starts it
// and letting go anywhere confirms, so the release listens on the window because the mic
// itself gives way to the confirm/discard pair while dictating.
function micHandlers(
  activation: VoiceActivationMode,
  startVoice: (mode: VoiceMode) => void,
  stopVoice: () => void,
): MicHandlers {
  if (activation === "toggle") {
    return {
      onClick: () => {
        startVoice("dictation");
      },
    };
  }
  return {
    onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
      e.preventDefault();
      startVoice("dictation");
      const release = () => {
        window.removeEventListener("pointerup", release);
        window.removeEventListener("pointercancel", release);
        if (useVoice.getState().recordingMode === "dictation") stopVoice();
      };
      window.addEventListener("pointerup", release);
      window.addEventListener("pointercancel", release);
    },
  };
}

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

// Expand a hair before the last word would wrap so the narrow field never shows two lines
// first; once expanded, hold until the text clearly fits again (hysteresis).
function expandedNext(
  prev: boolean,
  value: string,
  avail: number,
  width: number,
): boolean {
  if (value.trim().length === 0) return false;
  if (value.includes("\n")) return true;
  if (avail <= 0) return prev;
  return prev ? width > avail - 24 : width > avail - 8;
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
  const activation = useVoiceActivation((s) => s.mode);
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

interface ComposerControls {
  voiceConfigured: boolean;
  recordingMode: VoiceMode | null;
  inputDisabled: boolean;
  slot: "conversation" | "send";
  micHandlers: MicHandlers;
  onConfirm: () => void;
  onCancel: () => void;
  onConversation: () => void;
  onSend: () => void;
  canSend: boolean;
}

// The morph springs; a row flip or the exit morph rides the row spring; other growth is instant.
function heightTransition(inConversation: boolean, animated: boolean) {
  if (inConversation)
    return { type: "spring", stiffness: 300, damping: 32 } as const;
  return animated ? ROW_SPRING : { duration: 0 };
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
  onMorphSettled,
  onHeightAnimation,
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
  onMorphSettled?: () => void;
  onHeightAnimation?: (animating: boolean) => void;
}) {
  const { inputDisabled, recordingMode } = controls;

  // Expand (input onto its own full-width row above the buttons) once the text would wrap
  // past one line in the collapsed inline width. A hidden single-line mirror measured against
  // the cached collapsed input width keeps the decision stable, so it can't oscillate.
  const measureRef = useRef<HTMLSpanElement>(null);
  const collapsedWidthRef = useRef(0);
  const [expanded, setExpanded] = useState(false);
  // The box animates number-to-number, but only across the row transition (the wrap point
  // flipping) and the morph: each measurement carries whether the flip caused it, and any
  // other content growth (an extra textarea line, a chips row) applies instantly like a plain
  // textarea. The measurement pauses while the composer content is unmounted mid-conversation
  // (it would read 0 and must keep the last value).
  const animateNextHeightRef = useRef(false);
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
  }, [expanded, textareaRef]);
  useLayoutEffect(() => {
    const span = measureRef.current;
    if (!span) return;
    const next = expandedNext(
      expanded,
      value,
      collapsedWidthRef.current,
      span.scrollWidth,
    );
    if (next === expanded) return;
    // Only the row transition animates the box; growth within a state stays instant.
    animateNextHeightRef.current = true;
    setExpanded(next);
  }, [value, expanded]);

  const inConversation = recordingMode === "conversation";
  const [contentBox, setContentBox] = useState({ height: 0, animated: false });
  const measureContentRef = useMeasuredSize(
    "height",
    useCallback((height: number) => {
      if (height <= 0) return;
      setContentBox({ height, animated: animateNextHeightRef.current });
      animateNextHeightRef.current = false;
    }, []),
  );
  // The exit morph renders with inConversation already false, so the flip is what marks it as
  // still animated, until the morph's own completion clears it.
  const [conversation, setConversation] = useState({
    seen: inConversation,
    leaving: false,
  });
  if (conversation.seen !== inConversation) {
    setConversation({
      seen: inConversation,
      leaving: conversation.seen && !inConversation,
    });
  }
  const leavingConversation = conversation.leaving;
  return (
    <div className={paddingClass}>
      <m.div
        initial={false}
        // The composer pill morphs into the conversation panel: the box spring-animates its
        // height while the contents crossfade, so one surface reads as becoming the other.
        animate={{
          height: inConversation
            ? CONVERSATION_PANEL_HEIGHT
            : contentBox.height > 0
              ? contentBox.height
              : "auto",
        }}
        transition={heightTransition(
          inConversation,
          leavingConversation || contentBox.animated,
        )}
        // The morph's start is the parent's own conversation flip, so a typing animation never
        // trips the freeze; completion is safe to report from here (a settle outside a morph is
        // a no-op). The animation edges gate the parent's inset tracking, since mid-flight
        // heights must never become the list's reservation.
        onAnimationStart={() => onHeightAnimation?.(true)}
        onAnimationComplete={() => {
          setConversation((current) =>
            current.leaving ? { ...current, leaving: false } : current,
          );
          onHeightAnimation?.(false);
          onMorphSettled?.();
        }}
        // Contain the box so its animating height reflows only its own subtree, never the
        // chat above it.
        style={{ contain: "layout paint" }}
        className={cn(
          // rounded-3xl is half the collapsed height (48px): a true pill when collapsed. The
          // morphed conversation panel takes the design system's squircle corners instead.
          // Bottom-anchored: while the box grows toward wrapped content the clip edge reveals
          // the new top row and the button row never moves.
          "relative flex flex-col justify-end overflow-hidden border border-border bg-popover shadow-sm",
          inConversation
            ? "rounded-squircle-sm [corner-shape:squircle]"
            : "rounded-3xl",
          "has-[textarea:focus-visible]:ring-2 has-[textarea:focus-visible]:ring-ring/30",
          // Red snaps on with the recording and fades out slowly after it: the transition
          // class rides only the resting state, so the exit eases while the entry is instant.
          recordingMode === "dictation"
            ? "border-red-500"
            : "transition-colors duration-700",
        )}
      >
        {/* Default (sync) presence, not popLayout: popLayout absolutely positions and
            measures exiting children, forcing layout on every frame of the morph. The panel
            is absolutely positioned instead, so the two never fight for flow. */}
        <AnimatePresence initial={false}>
          {inConversation ? (
            <m.div
              key="conversation"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, transition: { duration: 0.12 } }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              className="absolute inset-0"
            >
              <ConversationPanel />
            </m.div>
          ) : (
            <m.div
              key="composer"
              ref={measureContentRef}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, transition: { duration: 0.12 } }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              className={cn(
                "flex flex-wrap items-end gap-1 px-2 pb-1.5",
                // Sides + bottom stay fixed so the bottom-row buttons don't move; only the top
                // grows to give the input its own breathing room on its own row.
                expanded ? "pt-3" : "pt-1.5",
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

              {/* position-only FLIP on the row pieces: the input glides onto its own row and
                  the buttons slide into place on the same spring the box grows with, while
                  the text itself never scale-distorts. */}
              <m.div
                layout="position"
                layoutDependency={expanded}
                transition={{ layout: ROW_SPRING }}
                className={cn("shrink-0", expanded ? "order-2" : "order-1")}
              >
                <AttachMenu
                  disabled={inputDisabled}
                  onFiles={attachments.addFiles}
                />
              </m.div>

              <m.div
                layout="position"
                layoutDependency={expanded}
                transition={{ layout: ROW_SPRING }}
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
                  data-voice-dictate="true"
                  placeholder={placeholder}
                  disabled={inputDisabled}
                  rows={1}
                  enterKeyHint="send"
                  className="field-sizing-content max-h-[240px] w-full resize-none bg-transparent px-1 py-1.5 leading-6 outline-none placeholder:text-muted-foreground disabled:opacity-50 md:text-base"
                />
              </m.div>

              <m.div
                layout="position"
                layoutDependency={expanded}
                transition={{ layout: ROW_SPRING }}
                className={cn(
                  "flex shrink-0 items-end gap-1 order-3",
                  expanded && "ml-auto",
                )}
              >
                <VoiceButtons controls={controls} />
              </m.div>
            </m.div>
          )}
        </AnimatePresence>
      </m.div>
    </div>
  );
}

// Height of the conversation surface the composer morphs into.
const CONVERSATION_PANEL_HEIGHT = 264;

// One spring for the pill growing toward wrapped text and the row pieces gliding within it,
// so the box and its contents arrive together.
const ROW_SPRING = { type: "spring", stiffness: 520, damping: 40 } as const;

const ACTION_BUTTON = "size-9 rounded-full [&_svg]:size-4";
function VoiceButtons({ controls }: { controls: ComposerControls }) {
  const {
    voiceConfigured,
    recordingMode,
    inputDisabled,
    slot,
    micHandlers,
    onConfirm,
    onCancel,
    onConversation,
    onSend,
    canSend,
  } = controls;

  // Voice never set up: the composer is a plain send box.
  if (!voiceConfigured) {
    return <SendButton disabled={inputDisabled || !canSend} onSend={onSend} />;
  }

  if (recordingMode === "dictation") {
    return (
      <>
        <Button
          type="button"
          size="icon"
          variant="secondary"
          onClick={onCancel}
          aria-label="discard dictation"
          title="discard dictation"
          className={ACTION_BUTTON}
        >
          <X />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="default"
          onClick={onConfirm}
          aria-label="send dictation"
          title="send dictation"
          className={ACTION_BUTTON}
        >
          <Check />
        </Button>
      </>
    );
  }

  const inConversation = recordingMode === "conversation";
  return (
    <>
      <div className="shrink-0">
        <Button
          type="button"
          size="icon"
          variant="secondary"
          disabled={inputDisabled || inConversation}
          {...micHandlers}
          aria-label="dictate"
          title="dictate"
          className={cn("touch-none", ACTION_BUTTON)}
        >
          <Mic />
        </Button>
      </div>
      {slot === "send" ? (
        <SendButton disabled={inputDisabled || !canSend} onSend={onSend} />
      ) : (
        <Button
          type="button"
          size="icon"
          variant="default"
          disabled={inputDisabled}
          onClick={onConversation}
          aria-label={
            inConversation ? "end conversation" : "start conversation"
          }
          title={inConversation ? "end conversation" : "start conversation"}
          className={cn(ACTION_BUTTON, inConversation && RECORDING_BUTTON)}
        >
          {inConversation ? <Square fill="currentColor" /> : <AudioLines />}
        </Button>
      )}
    </>
  );
}

function SendButton({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: () => void;
}) {
  return (
    <Button
      type="button"
      size="icon"
      variant="ghost"
      aria-label="send message"
      disabled={disabled}
      onClick={onSend}
      className={ACTION_BUTTON}
    >
      <SendHorizontal />
    </Button>
  );
}
