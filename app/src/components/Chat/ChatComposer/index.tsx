import type { ChangeEvent, KeyboardEvent, RefObject } from "react";
import { Mic, SendHorizontal, Square } from "lucide-react";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import { cn } from "@/lib/utils";

interface ChatComposerProps {
  fullscreen?: boolean;
  connected: boolean;
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
  connected,
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
      <InputGroup
        className={cn(
          "min-h-12 px-1",
          isRecording &&
          "ring-2 ring-red-500 has-[[data-slot=input-group-control]:focus-visible]:border-transparent has-[[data-slot=input-group-control]:focus-visible]:ring-2 has-[[data-slot=input-group-control]:focus-visible]:ring-red-500",
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
