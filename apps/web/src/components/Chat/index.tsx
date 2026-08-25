import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CHAT_CONTENT_WIDTH } from "./content-width";
import { useToast } from "@/stores/use-toast";
import { useLayout } from "@/stores/use-layout";
import { useAgentSocket } from "@/providers/AgentSocketProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/stores/use-voice";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { BottomBanner } from "./BottomBanner";
import { ChatComposer } from "./ChatComposer";
import { ChatHeaderActions } from "./ChatHeaderActions";
import { ChatMessageArea, type ChatScrollHandle } from "./ChatMessageArea";
import { useChatKeyboardFocus } from "./use-chat-keyboard-focus";
import { agentNeedsUser } from "@vesta/core";

// Breathing room between the last bubble and the floating composer, folded into
// the inset so the message list, skeleton, mask, and button all clear it.
const COMPOSER_GAP_FULLSCREEN_PX = 12;
const COMPOSER_GAP_PANEL_PX = 8;

interface ChatProps {
  onCollapse?: () => void;
  fullscreen?: boolean;
}

export function Chat({ onCollapse, fullscreen }: ChatProps = {}) {
  const { name, agent } = useSelectedAgent();
  const notAuthenticated = agentNeedsUser(agent.status);
  const isMobile = useIsMobile();
  const toast = useToast();
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const {
    sttAvailable,
    voiceAutoSend,
    isRecording,
    liveTranscript,
    toggleVoice,
    voiceError,
    registerChatCallbacks,
    isSpeaking,
    stopSpeech,
  } = useVoice();

  const {
    messages,
    isTyping,
    connected,
    historyLoaded,
    hasMore,
    loadingMore,
    loadMore,
    send,
    retry,
  } = useAgentSocket();

  const [input, setInput] = useState("");
  const [atBottom, setAtBottom] = useState(true);

  useEffect(() => {
    registerChatCallbacks(send, setInput);
  }, [registerChatCallbacks, send]);

  const scrollRef = useRef<ChatScrollHandle>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useChatKeyboardFocus(textareaRef);

  // Every chat floats the composer over the message list; the messages reserve
  // its live height plus the gap at the bottom so the last one always clears it,
  // and the scroll-to-bottom button parks just above it.
  const composerRef = useRef<HTMLDivElement>(null);
  const [composerInset, setComposerInset] = useState(0);
  // The inset tracks the composer's collapsed baseline only: a growing draft
  // expands the pill over the (masked, opaque-covered) list instead of shifting
  // it, so measurements while a draft exists are ignored; send clears the draft
  // and the next resize re-syncs the baseline.
  const hasDraftRef = useRef(false);
  useLayoutEffect(() => {
    hasDraftRef.current = input.length > 0;
  });
  useLayoutEffect(() => {
    const el = composerRef.current;
    if (!el) {
      setComposerInset(0);
      return;
    }
    // Measure synchronously before first paint (ResizeObserver callbacks are
    // async, and waiting for one paints a frame with no inset reserved); the
    // observer covers later composer resizes.
    setComposerInset(el.offsetHeight);
    const ro = new ResizeObserver(() => {
      if (!hasDraftRef.current) setComposerInset(el.offsetHeight);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const chatMessages = useMemo(
    () =>
      messages.filter(
        (m) =>
          m.type === "user" ||
          m.type === "chat" ||
          m.type === "error" ||
          m.type === "rate_limited",
      ),
    [messages],
  );

  const scrollToBottom = useCallback(() => {
    scrollRef.current?.scrollToBottom();
  }, []);

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
    if (!connected) {
      toast.error(`can't reach ${name} right now, message not sent`);
      return;
    }
    if (send(text)) {
      setInput("");
      const ta = textareaRef.current;
      if (ta) ta.style.height = "auto";
      requestAnimationFrame(scrollToBottom);
    }
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = `${String(Math.min(ta.scrollHeight, 240))}px`;
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Card
        className={cn(
          "flex flex-col h-full gap-0 py-0 px-0 overflow-hidden relative text-base shadow-none",
          fullscreen && "ring-0",
          isMobile && "bg-transparent overflow-visible",
        )}
      >
        <ChatHeaderActions
          fullscreen={fullscreen}
          onCollapse={onCollapse}
          agentName={name}
        />

        <ChatMessageArea
          scrollRef={scrollRef}
          loadMore={() => {
            void loadMore();
          }}
          fullscreen={fullscreen}
          navbarHeight={navbarHeight}
          loadingMore={loadingMore}
          hasMore={hasMore}
          chatMessages={chatMessages}
          connected={connected}
          historyLoaded={historyLoaded}
          agentName={name}
          notAuthenticated={notAuthenticated}
          isTyping={isTyping}
          isMobile={isMobile}
          onRetry={retry}
          bottomInset={
            composerInset +
            (fullscreen ? COMPOSER_GAP_FULLSCREEN_PX : COMPOSER_GAP_PANEL_PX)
          }
          onAtBottomChange={setAtBottom}
        />

        <div
          ref={composerRef}
          // px-3 mirrors the message list's 12px scrollbar-gutter on each side, so the
          // composer's w-3/5 column computes from the same width and lines up with the bubbles.
          className={cn("absolute inset-x-0 bottom-0", !isMobile && "px-3")}
        >
          {chatMessages.length > 0 && (
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Scroll to latest message"
              data-active={!atBottom}
              onClick={scrollToBottom}
              className={cn(
                "absolute bottom-full left-1/2 z-10 mb-3 -translate-x-1/2 rounded-full shadow-sm transition-all duration-200",
                "data-[active=false]:pointer-events-none data-[active=false]:translate-y-full data-[active=false]:scale-95 data-[active=false]:opacity-0 data-[active=false]:duration-150 data-[active=false]:ease-[cubic-bezier(0.7,0,0.84,0)]",
                "data-[active=true]:translate-y-0 data-[active=true]:scale-100 data-[active=true]:opacity-100 data-[active=true]:ease-[cubic-bezier(0.23,1,0.32,1)]",
              )}
            >
              <ArrowDown />
            </Button>
          )}
          <div
            className={cn(
              "relative",
              // 60% centered column is fullscreen-only; the split-panel composer fills its panel.
              fullscreen && !isMobile && CHAT_CONTENT_WIDTH,
            )}
          >
            <BottomBanner error={voiceError} />
            <ChatComposer
              fullscreen={fullscreen}
              agentName={name}
              notAuthenticated={notAuthenticated}
              sttAvailable={sttAvailable}
              isRecording={isRecording}
              voiceAutoSend={voiceAutoSend}
              liveTranscript={liveTranscript}
              toggleVoice={toggleVoice}
              isSpeaking={isSpeaking}
              onStopSpeech={stopSpeech}
              input={input}
              onInputChange={handleInput}
              onKeyDown={handleKeyDown}
              onSend={handleSend}
              textareaRef={textareaRef}
            />
          </div>
        </div>
      </Card>
    </div>
  );
}
