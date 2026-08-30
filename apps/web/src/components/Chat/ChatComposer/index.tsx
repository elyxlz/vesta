import {
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
} from "react";
import {
  AudioLines,
  Check,
  Mic,
  Plus,
  SendHorizontal,
  Square,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useVoice, type VoiceMode } from "@/stores/use-voice";
import {
  useVoiceActivation,
  type VoiceActivationMode,
} from "@/stores/use-voice-activation";
import { useIsMobile } from "@/hooks/use-mobile";
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
  isSpeaking,
  notAuthenticated,
  agentName,
}: {
  recordingMode: VoiceMode | null;
  listening: boolean;
  isSpeaking: boolean;
  notAuthenticated: boolean;
  agentName: string;
}) {
  if (recordingMode !== null) {
    if (!listening) return "connecting...";
    if (recordingMode === "conversation" && isSpeaking) return "speaking...";
    return "listening...";
  }
  return notAuthenticated
    ? "sign in to chat"
    : `message ${agentName}`.toLowerCase();
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
  recordingMode: VoiceMode | null;
  listening: boolean;
  isSpeaking: boolean;
  liveTranscript: string;
  startVoice: (mode: VoiceMode) => void;
  stopVoice: () => void;
  cancelVoice: () => void;
  input: string;
  onInputChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: KeyboardEvent) => void;
  onSend: () => void;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}

export function ChatComposer({
  fullscreen,
  agentName,
  notAuthenticated,
  sttAvailable,
  recordingMode,
  listening,
  isSpeaking,
  liveTranscript,
  startVoice,
  stopVoice,
  cancelVoice,
  input,
  onInputChange,
  onKeyDown,
  onSend,
  textareaRef,
}: ChatComposerProps) {
  const isMobile = useIsMobile();
  const activation = useVoiceActivation((s) => s.mode);
  // The input shows what dictation has captured so far, or a conversation's live turn.
  const useLiveTranscript = recordingMode !== null;
  // Only sign-in disables the field; a dropped connection still lets you type (a send while
  // disconnected is blocked with a toast in the parent instead).
  const inputDisabled = notAuthenticated;
  const value = useLiveTranscript ? liveTranscript : input;
  const placeholder = placeholderText({
    recordingMode,
    listening,
    isSpeaking,
    notAuthenticated,
    agentName,
  });
  const controls: ComposerControls = {
    sttAvailable,
    recordingMode,
    inputDisabled,
    slot: rightSlot({ input, recordingMode }),
    micHandlers: micHandlers(activation, startVoice, stopVoice),
    onConfirm: stopVoice,
    onCancel: cancelVoice,
    onConversation: () => {
      if (recordingMode === "conversation") stopVoice();
      else startVoice("conversation");
    },
    onSend,
  };

  return (
    <FloatingComposer
      paddingClass={composerPadding(fullscreen, isMobile)}
      value={value}
      placeholder={placeholder}
      readOnly={useLiveTranscript}
      onInputChange={onInputChange}
      onKeyDown={onKeyDown}
      textareaRef={textareaRef}
      controls={controls}
    />
  );
}

interface ComposerControls {
  sttAvailable: boolean;
  recordingMode: VoiceMode | null;
  inputDisabled: boolean;
  slot: "conversation" | "send";
  micHandlers: MicHandlers;
  onConfirm: () => void;
  onCancel: () => void;
  onConversation: () => void;
  onSend: () => void;
}

function FloatingComposer({
  paddingClass,
  value,
  placeholder,
  readOnly,
  onInputChange,
  onKeyDown,
  textareaRef,
  controls,
}: {
  paddingClass: string;
  value: string;
  placeholder: string;
  readOnly: boolean;
  onInputChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: KeyboardEvent) => void;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  controls: ComposerControls;
}) {
  const { inputDisabled, recordingMode } = controls;

  // Expand (input onto its own full-width row above the buttons) once the text would wrap
  // past one line in the collapsed inline width. A hidden single-line mirror measured against
  // the cached collapsed input width keeps the decision stable, so it can't oscillate.
  const measureRef = useRef<HTMLSpanElement>(null);
  const collapsedWidthRef = useRef(0);
  const [expanded, setExpanded] = useState(false);
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
      <div
        className={cn(
          // rounded-3xl is half the collapsed height (48px): a true pill when collapsed, the same
          // corners as a rounded rectangle once it grows.
          "flex flex-wrap items-end gap-1 rounded-3xl border border-border bg-popover px-2 pb-1.5 shadow-sm",
          // Sides + bottom stay fixed so the bottom-row buttons don't move; only the top grows
          // to give the input its own breathing room once it moves onto its own row.
          expanded ? "pt-3" : "pt-1.5",
          "has-[textarea:focus-visible]:ring-2 has-[textarea:focus-visible]:ring-ring/30",
          recordingMode !== null && "border-red-500",
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

        <div className={cn("shrink-0", expanded ? "order-2" : "order-1")}>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label="add attachment"
            className="size-9 rounded-full text-muted-foreground [&_svg]:size-5"
          >
            <Plus />
          </Button>
        </div>

        <div
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
            readOnly={readOnly}
            data-voice-dictate="true"
            placeholder={placeholder}
            disabled={inputDisabled}
            rows={1}
            enterKeyHint="send"
            className="field-sizing-content max-h-[240px] w-full resize-none bg-transparent px-1 py-1.5 leading-6 outline-none placeholder:text-muted-foreground disabled:opacity-50 md:text-base"
          />
        </div>

        <div
          className={cn(
            "flex shrink-0 items-end gap-1 order-3",
            expanded && "ml-auto",
          )}
        >
          <VoiceButtons controls={controls} />
        </div>
      </div>
    </div>
  );
}

const ACTION_BUTTON = "size-9 rounded-full [&_svg]:size-4";
const RECORDING_BUTTON = "bg-red-500 text-white hover:bg-red-600";

function VoiceButtons({ controls }: { controls: ComposerControls }) {
  const {
    sttAvailable,
    recordingMode,
    inputDisabled,
    slot,
    micHandlers,
    onConfirm,
    onCancel,
    onConversation,
    onSend,
  } = controls;

  if (!sttAvailable) {
    return <SendButton disabled={inputDisabled} onSend={onSend} />;
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
        <SendButton disabled={inputDisabled} onSend={onSend} />
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
