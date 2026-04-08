import type { KeyboardEvent, RefObject } from "react";
import { Mic, SendHorizontal, Square } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ThinkingDots } from "../ThinkingDots";
import { thinkingIndicatorVariants } from "../thinking-indicator-variants";

interface ChatComposerProps {
  fullscreen?: boolean;
  isThinking: boolean;
  wasConnected: boolean;
  connected: boolean;
  voiceError: string | null;
  sttAvailable: boolean;
  isRecording: boolean;
  voiceAutoSend: boolean;
  liveTranscript: string;
  toggleVoice: () => void;
  input: string;
  onInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: KeyboardEvent) => void;
  onSend: () => void;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}

export function ChatComposer({
  fullscreen,
  isThinking,
  wasConnected,
  connected,
  voiceError,
  sttAvailable,
  isRecording,
  voiceAutoSend,
  liveTranscript,
  toggleVoice,
  input,
  onInputChange,
  onKeyDown,
  onSend,
  textareaRef,
}: ChatComposerProps) {
  return (
    <div className={cn("shrink-0 flex flex-col gap-0 pt-0", fullscreen ? "px-page pb-page" : "px-2.5 pb-2.5")}>
      <AnimatePresence>
        {isThinking && (
          <motion.div
            variants={thinkingIndicatorVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="shrink-0 overflow-hidden"
          >
            <div className="px-3 pb-2">
              <ThinkingDots className="py-0" />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {wasConnected && !connected && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="flex items-center justify-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-1.5 mb-3 mx-auto w-fit text-xs text-amber-600 dark:text-amber-400">
              reconnecting...
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {voiceError && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="flex justify-center pb-2">
              <span className="rounded-full border border-destructive/20 bg-destructive/5 px-3 py-1 text-xs text-destructive">
                {voiceError}
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <div className={cn(
        "flex items-center gap-2.5 w-full rounded-xl border bg-card shadow-md px-4 min-h-12",
        isRecording && "border-red-500/50",
      )}>
        {isRecording && voiceAutoSend ? (
          <div className="flex-1 py-2.5 text-base sm:text-sm leading-5 text-foreground min-h-5">
            {liveTranscript || <span className="text-muted-foreground/50 animate-pulse">listening...</span>}
          </div>
        ) : (
          <textarea
            ref={textareaRef}
            value={input}
            onChange={onInputChange}
            onKeyDown={onKeyDown}
            placeholder={isRecording ? "listening..." : connected ? "send a message..." : "connecting..."}
            disabled={!connected}
            rows={1}
            enterKeyHint="send"
            className="m-0 flex-1 min-h-5 max-h-[120px] bg-transparent py-2.5 text-base sm:text-sm leading-5 resize-none outline-none placeholder:text-muted-foreground/50 disabled:opacity-50"
          />
        )}
        {sttAvailable && (
          <Button
            size="icon-sm"
            variant="ghost"
            className="shrink-0"
            disabled={!connected}
            onClick={toggleVoice}
          >
            {isRecording ? (
              <Square className="text-red-500" size={14} />
            ) : (
              <Mic className="text-muted-foreground" />
            )}
          </Button>
        )}
        {(!isRecording || !voiceAutoSend) && (
          <Button
            size="icon-sm"
            variant="ghost"
            className="shrink-0"
            disabled={!connected || !input.trim()}
            onClick={onSend}
          >
            <SendHorizontal className="text-muted-foreground" />
          </Button>
        )}
      </div>
    </div>
  );
}
