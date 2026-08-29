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
import { useLocation } from "react-router-dom";
import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CHAT_CONTENT_COLUMN } from "./content-column";
import { useToast } from "@/stores/use-toast";
import { useLayout, type ComposerVariant } from "@/stores/use-layout";
import { useAgentSocket } from "@/providers/AgentSocketProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/stores/use-voice";
import { useChatDraft } from "@/stores/use-chat-draft";
import { useIsMobile } from "@/hooks/use-mobile";
import { useMeasuredSize } from "@/hooks/use-measured-size";
import { cn } from "@/lib/utils";
import { BottomBanner } from "./BottomBanner";
import { ChatComposer } from "./ChatComposer";
import { ChatHeaderActions } from "./ChatHeaderActions";
import { ChatMessageArea, type ChatScrollHandle } from "./ChatMessageArea";
import { useChatKeyboardFocus } from "./use-chat-keyboard-focus";
import { agentSubpage } from "@/lib/agent-subpage";
import { TRIM_HISTORY_SETTLE_MS, agentNeedsUser } from "@vesta/core";

// Breathing room between the last bubble and the floating composer, folded into
// the inset so the message list, skeleton, mask, and button all clear it.
const COMPOSER_GAP_FULLSCREEN_PX = 12;
const COMPOSER_GAP_PANEL_PX = 8;

// The empty composer's height per layout, a CSS-deterministic baseline: the 50px
// pill (a 36px button row plus its 6+6px padding and 2px border) plus the
// wrapper's bottom gap (pb-3 12 / pb-4 16 / pb-1 4). Seeds a cold remount so the
// list reserves the composer's space on its first render; the real measurement
// then overwrites it.
const COMPOSER_BASELINE_PX: Record<ComposerVariant, number> = {
  panel: 62,
  fullscreen: 66,
  mobile: 54,
};

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
    trimHistory,
    send,
    retry,
  } = useAgentSocket();

  const [input, setInput] = useChatDraft(name);
  const [atBottom, setAtBottom] = useState(true);

  useEffect(() => {
    if (!atBottom) return;
    const timer = window.setTimeout(trimHistory, TRIM_HISTORY_SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [atBottom, trimHistory]);

  useEffect(() => {
    registerChatCallbacks(send, setInput);
  }, [registerChatCallbacks, send, setInput]);

  const scrollRef = useRef<ChatScrollHandle>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useChatKeyboardFocus(textareaRef);

  // Focus the composer whenever the chat becomes the visible surface: on mount,
  // and again when a logs/settings subpage closes (the pane stays mounted, so a
  // mount-time autofocus never refires). Skipped on mobile, where autofocus
  // would raise the keyboard on every open. A fullscreen and a panel Chat can
  // both be mounted; focus() is a no-op on the visibility-hidden one.
  const { pathname } = useLocation();
  useEffect(() => {
    if (isMobile || agentSubpage(pathname, name) !== null) return;
    textareaRef.current?.focus({ preventScroll: true });
  }, [isMobile, pathname, name]);

  // Every chat floats the composer over the message list; the messages reserve
  // its live height plus the gap at the bottom so the last one always clears it,
  // and the scroll-to-bottom button parks just above it.
  // Seed so a remounted chat (reopened from collapse) reserves the composer's space
  // on its first render, before the async measure lands; measuring the same value
  // then makes no re-pin, so bubbles don't snap. The cache holds the exact measured
  // height once the composer has mounted this session; a cold mount falls back to the
  // hardcoded baseline, which the real measurement overwrites.
  const composerVariant: ComposerVariant = isMobile
    ? "mobile"
    : fullscreen
      ? "fullscreen"
      : "panel";
  const setComposerBaseline = useLayout((s) => s.setComposerBaseline);
  const seedBaseline = () =>
    useLayout.getState().composerBaseline[composerVariant] ||
    COMPOSER_BASELINE_PX[composerVariant];
  const [composerInset, setComposerInset] = useState(seedBaseline);
  const [composerHeight, setComposerHeight] = useState(seedBaseline);
  // The inset tracks the composer's collapsed baseline only: a growing draft
  // expands the pill over the (masked, opaque-covered) list instead of shifting
  // it, so measurements while a draft exists are ignored (a cleared inset, 0,
  // always applies); send clears the draft and the next resize re-syncs. The
  // live height is tracked separately: its overhang beyond the baseline extends
  // the message list's scroll range, so the bubbles a tall draft covers stay
  // reachable by scrolling without the list ever shifting under the typist.
  const hasDraftRef = useRef(false);
  useLayoutEffect(() => {
    hasDraftRef.current = input.length > 0;
  });
  const composerRef = useMeasuredSize(
    "height",
    useCallback(
      (height: number) => {
        setComposerHeight(height);
        if (height === 0 || !hasDraftRef.current) {
          setComposerInset(height);
          // Cache only a real, draft-free baseline; unmount reports 0, which must
          // not overwrite the seed the next remount reads.
          if (height > 0) setComposerBaseline(composerVariant, height);
        }
      },
      [composerVariant, setComposerBaseline],
    ),
  );

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

  // Stable so ChatMessageArea's memo holds across per-keystroke composer re-renders.
  const handleLoadMore = useCallback(() => {
    void loadMore();
  }, [loadMore]);

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
          loadMore={handleLoadMore}
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
          bottomOverhang={Math.max(0, composerHeight - composerInset)}
          onAtBottomChange={setAtBottom}
        />

        <div
          ref={composerRef}
          // px-3 mirrors the message list's 12px scrollbar-gutter on each side, so the
          // composer's capped column computes from the same width and lines up with the bubbles.
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
              // The capped centered column is shared by both desktop chats; only mobile fills full width.
              !isMobile && CHAT_CONTENT_COLUMN,
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
