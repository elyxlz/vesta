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
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { useLayout } from "@/stores/use-layout";
import { useChatContext } from "@/providers/ChatProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useVoice } from "@/providers/VoiceProvider";
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
  const setInputCb = useCallback((text: string) => {
    setInput(text);
  }, []);

  useEffect(() => {
    registerChatCallbacks(send, setInputCb);
  }, [registerChatCallbacks, send, setInputCb]);

  const [wasConnected, setWasConnected] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const prevMsgCountRef = useRef(0);
  const scrollHeightBeforeLoad = useRef(0);
  const { check, scroll, scrollToBottom, isNearBottom } = useAutoScroll();
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

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const prevCount = prevMsgCountRef.current;
    const newCount = chatMessages.length;
    if (newCount > prevCount && prevCount > 0 && el.scrollTop < 50) {
      el.scrollTop = el.scrollHeight - scrollHeightBeforeLoad.current;
    } else if (newCount > prevCount && !isNearBottom) {
      const latest = chatMessages[newCount - 1];
      if (latest && latest.type !== "user") setHasNewMessage(true);
    } else {
      scroll(el);
    }
    prevMsgCountRef.current = newCount;
  }, [chatMessages, scroll, isNearBottom]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    scroll(el);
    const id = setInterval(() => scroll(el), 16);
    const timeout = setTimeout(() => clearInterval(id), 300);
    return () => {
      clearInterval(id);
      clearTimeout(timeout);
    };
  }, [isThinking, scroll]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !hasMore || loadingMore) return;
    if (el.scrollHeight <= el.clientHeight) {
      scrollHeightBeforeLoad.current = el.scrollHeight;
      loadMore();
    }
  }, [chatMessages, hasMore, loadingMore, loadMore]);

  const handleScroll = useCallback(() => {
    check(scrollRef.current);
    const el = scrollRef.current;
    if (el && el.scrollTop < 100 && hasMore && !loadingMore) {
      scrollHeightBeforeLoad.current = el.scrollHeight;
      loadMore();
    }
  }, [check, hasMore, loadingMore, loadMore]);

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
    if (send(text)) {
      setInput("");
      const ta = textareaRef.current;
      if (ta) ta.style.height = "auto";
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
    <Card
      className={
        "flex flex-col h-full gap-0 py-0 px-0 overflow-hidden relative text-base"
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
        onScrollToBottom={() => scrollToBottom(scrollRef.current)}
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
  );
}
