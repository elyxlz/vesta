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
import { Card } from "@/components/ui/card";
import { useLayout } from "@/stores/use-layout";
import { useChatContext } from "@/providers/ChatProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/providers/VoiceProvider";
import { cn } from "@/lib/utils";
import { ChatComposer } from "./ChatComposer";
import { ChatHeaderActions } from "./ChatHeaderActions";
import { ChatMessageArea } from "./ChatMessageArea";

interface ChatProps {
  onCollapse?: () => void;
  fullscreen?: boolean;
}

export function Chat({ onCollapse, fullscreen }: ChatProps = {}) {
  const { name } = useSelectedAgent();
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const {
    sttAvailable,
    voiceAutoSend,
    isRecording,
    liveTranscript,
    toggleVoice,
    voiceError,
    registerChatCallbacks,
  } = useVoice();

  const {
    messages,
    agentState,
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

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const prevMsgCountRef = useRef(0);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [hasNewMessage, setHasNewMessage] = useState(false);

  useEffect(() => {
    if (connected) setWasConnected(true);
  }, [connected]);

  useEffect(() => {
    if (isNearBottom) setHasNewMessage(false);
  }, [isNearBottom]);

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

  const isThinking = agentState === "thinking";

  // column-reverse: scrollTop=0 is bottom, browser keeps scrollTop stable on prepend
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const prevCount = prevMsgCountRef.current;
    const newCount = chatMessages.length;

    if (newCount > prevCount && prevCount > 0) {
      if (!isNearBottom) {
        const latest = chatMessages[newCount - 1];
        if (latest && latest.type !== "user") setHasNewMessage(true);
      }
    }
    prevMsgCountRef.current = newCount;
  }, [chatMessages, isNearBottom]);

  // Initial fill: if content doesn't fill the viewport, load more
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !hasMore || loadingMore) return;
    if (el.scrollHeight <= el.clientHeight) {
      loadMore();
    }
  }, [chatMessages, hasMore, loadingMore, loadMore]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;

    const nearBottom = el.scrollTop <= 80;
    if (nearBottom !== isNearBottom) setIsNearBottom(nearBottom);

    const distanceFromTop = el.scrollHeight - el.clientHeight + el.scrollTop;
    if (distanceFromTop < 100 && hasMore && !loadingMore) {
      loadMore();
    }
  }, [isNearBottom, hasMore, loadingMore, loadMore]);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = 0;
    setIsNearBottom(true);
  }, []);

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
    if (send(text)) {
      setInput("");
      const ta = textareaRef.current;
      if (ta) ta.style.height = "auto";
      scrollToBottom();
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
        fullscreen && "drop-shadow-md",
      )}
    >
    <Card
      className={cn(
        "flex flex-col h-full gap-0 py-0 px-0 overflow-hidden relative text-base",
        fullscreen && "shadow-none ring-0",
      )}
      style={
        fullscreen
          ? { maskImage: `linear-gradient(to bottom, transparent, black ${navbarHeight * 3.5}px)` }
          : undefined
      }
    >
      <ChatHeaderActions
        fullscreen={fullscreen}
        onCollapse={onCollapse}
        agentName={name}
      />

      <ChatMessageArea
        scrollRef={scrollRef}
        onScroll={handleScroll}
        fullscreen={fullscreen}
        navbarHeight={navbarHeight}
        hasNewMessage={hasNewMessage}
        onScrollToBottom={scrollToBottom}
        loadingMore={loadingMore}
        hasMore={hasMore}
        chatMessages={chatMessages}
        connected={connected}
        agentName={name}
      />

      <ChatComposer
        fullscreen={fullscreen}
        isThinking={isThinking}
        wasConnected={wasConnected}
        connected={connected}
        voiceError={voiceError}
        sttAvailable={sttAvailable}
        isRecording={isRecording}
        voiceAutoSend={voiceAutoSend}
        liveTranscript={liveTranscript}
        toggleVoice={toggleVoice}
        input={input}
        onInputChange={handleInput}
        onKeyDown={handleKeyDown}
        onSend={handleSend}
        textareaRef={textareaRef}
      />
    </Card>
    </div>
  );
}
