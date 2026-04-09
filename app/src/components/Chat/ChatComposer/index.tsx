import type { ChangeEvent, KeyboardEvent, RefObject } from "react";
import { Mic, SendHorizontal, Square } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
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
  onInputChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
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
    <div
      className={cn(
        fullscreen ? "px-[calc(var(--page-padding-x)/2)] pb-[calc(var(--page-padding-x)/2)]" : "px-2.5 pb-2.5",
   
      )}
    >
      <AnimatePresence>
        {isThinking && (
          <motion.div
            variants={thinkingIndicatorVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="shrink-0 overflow-hidden"
          >
            <div className="px-4 pt-2 pb-1">
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
            <div className="flex justify-center p-2">
              <Alert className="w-fit rounded-full border-warning/20 bg-warning/5 px-3 py-1.5">
                <AlertDescription className="text-xs text-warning">
                  reconnecting...
                </AlertDescription>
              </Alert>
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
              <Alert
                variant="destructive"
                className="w-fit rounded-full border-destructive/20 bg-destructive/5 px-3 py-1"
              >
                <AlertDescription className="text-xs">
                  {voiceError}
                </AlertDescription>
              </Alert>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <InputGroup
        className={cn(
          "min-h-12 px-1",
          isRecording &&
          "border-red-500/50 has-[[data-slot=input-group-control]:focus-visible]:border-red-500/50 has-[[data-slot=input-group-control]:focus-visible]:ring-red-500/20",
        )}
      >
        <InputGroupTextarea
          ref={textareaRef}
          value={isRecording && voiceAutoSend ? liveTranscript : input}
          onChange={onInputChange}
          onKeyDown={onKeyDown}
          readOnly={isRecording && voiceAutoSend}
          placeholder={
            isRecording
              ? "listening..."
              : "send a message..."
          }
          disabled={!connected}
          rows={1}
          enterKeyHint="send"
          className="max-h-[120px] md:text-base"
        />
        {(sttAvailable || !isRecording || !voiceAutoSend) && (
          <InputGroupAddon align="inline-end">
            {sttAvailable && (
              <InputGroupButton
                size="icon-sm"
                variant="ghost"
                disabled={!connected}
                onClick={toggleVoice}
              >
                {isRecording ? (
                  <Square
                    className="text-red-500"
                    fill="currentColor"
                  />
                ) : (
                  <Mic />
                )}
              </InputGroupButton>
            )}
            {(!isRecording || !voiceAutoSend) && (
              <InputGroupButton
                size="icon-sm"
                variant="ghost"
                disabled={!connected}
                onClick={onSend}
              >
                <SendHorizontal />
              </InputGroupButton>
            )}
          </InputGroupAddon>
        )}
      </InputGroup>
    </div>
  );
}
