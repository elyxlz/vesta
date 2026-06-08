import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import type { VirtuosoHandle } from "react-virtuoso";
import { Card } from "@/components/ui/card";
import { useLayout } from "@/stores/use-layout";
import { useChatContext } from "@/providers/ChatProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/stores/use-voice";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { BottomBanner } from "./BottomBanner";
import { ChatComposer } from "./ChatComposer";
import { ChatHeaderActions } from "./ChatHeaderActions";
import { ChatMessageArea } from "./ChatMessageArea";
import { useChatKeyboardFocus } from "./use-chat-keyboard-focus";

interface ChatProps {
  onCollapse?: () => void;
  fullscreen?: boolean;
}

export function Chat({ onCollapse, fullscreen }: ChatProps = {}) {
  const { name } = useSelectedAgent();
  const isMobile = useIsMobile();
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
    hasMore,
    loadingMore,
    loadMore,
    send,
    showToolCalls,
  } = useChatContext();

  const [input, setInput] = useState("");

  useEffect(() => {
    registerChatCallbacks(send, setInput);
  }, [registerChatCallbacks, send]);

  const [wasConnected, setWasConnected] = useState(false);

  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomVisibleRef = useRef(true);
  const [hasNewMessage, setHasNewMessage] = useState(false);
  useChatKeyboardFocus(textareaRef);

  useEffect(() => {
    if (connected) setWasConnected(true);
  }, [connected]);

  const chatMessages = useMemo(
    () =>
      messages.filter(
        (m) =>
          m.type === "user" ||
          m.type === "chat" ||
          m.type === "error" ||
          (showToolCalls &&
            m.type === "tool_start" &&
            !(m.tool === "Bash" && m.input.includes("app-chat"))),
      ),
    [messages, showToolCalls],
  );

  const lastMsgRef = useRef<string | null>(null);

  useEffect(() => {
    const latest = chatMessages[chatMessages.length - 1];
    const latestKey = latest ? `${latest.ts}-${latest.type}` : null;
    const prev = lastMsgRef.current;
    lastMsgRef.current = latestKey;

    if (prev && latestKey && latestKey !== prev && !bottomVisibleRef.current) {
      if (latest.type !== "user") setHasNewMessage(true);
    }
  }, [chatMessages]);

  const handleStartReached = useCallback(() => {
    if (hasMore && !loadingMore) loadMore();
  }, [hasMore, loadingMore, loadMore]);

  const handleAtBottomChange = useCallback((atBottom: boolean) => {
    bottomVisibleRef.current = atBottom;
    if (atBottom) setHasNewMessage(false);
  }, []);

  const scrollToBottom = useCallback(() => {
    virtuosoRef.current?.scrollToIndex({ index: "LAST", behavior: "smooth" });
  }, []);

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
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
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  };

  return (
    <div
      className={cn(
        "flex flex-col h-full min-h-0",
        fullscreen && !isMobile && "drop-shadow-md",
      )}
    >
      <Card
        className={cn(
          "flex flex-col h-full gap-0 py-0 px-0 overflow-hidden relative text-base",
          fullscreen && "shadow-none ring-0",
          isMobile && "bg-transparent overflow-visible",
        )}
        style={
          fullscreen
            ? {
                maskImage: `linear-gradient(to bottom, transparent, black ${navbarHeight * (isMobile ? 1.75 : 3.5)}px)`,
              }
            : undefined
        }
      >
        <ChatHeaderActions
          fullscreen={fullscreen}
          onCollapse={onCollapse}
          agentName={name}
        />

        <ChatMessageArea
          virtuosoRef={virtuosoRef}
          onStartReached={handleStartReached}
          onAtBottomStateChange={handleAtBottomChange}
          fullscreen={fullscreen}
          navbarHeight={navbarHeight}
          loadingMore={loadingMore}
          hasMore={hasMore}
          chatMessages={chatMessages}
          connected={connected}
          agentName={name}
          isTyping={isTyping}
          isMobile={isMobile}
        />

        <div className="relative">
          <BottomBanner
            hasNewMessage={hasNewMessage}
            onScrollToBottom={scrollToBottom}
            wasConnected={wasConnected}
            connected={connected}
            error={voiceError}
          />
          <ChatComposer
            fullscreen={fullscreen}
            connected={connected}
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
      </Card>
    </div>
  );
}
