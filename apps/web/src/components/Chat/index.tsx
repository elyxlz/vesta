import {
  useCallback,
  useEffect,
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
import { useVoice } from "@/stores/use-voice";
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
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomVisibleRef = useRef(true);
  const [hasNewMessage, setHasNewMessage] = useState(false);
  useChatKeyboardFocus(textareaRef);

  useEffect(() => {
    if (connected) setWasConnected(true);
  }, [connected]);

  useEffect(() => {
    const el = bottomRef.current;
    const root = scrollRef.current;
    if (!el || !root) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        bottomVisibleRef.current = entry.isIntersecting;
        if (entry.isIntersecting) setHasNewMessage(false);
      },
      { root, threshold: 0 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

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

    const distanceFromTop = el.scrollHeight - el.clientHeight + el.scrollTop;
    if (distanceFromTop < 100 && hasMore && !loadingMore) {
      loadMore();
    }
  }, [hasMore, loadingMore, loadMore]);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: 0, behavior: "smooth" });
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
            ? {
                maskImage: `linear-gradient(to bottom, transparent, black ${navbarHeight * 3.5}px)`,
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
          scrollRef={scrollRef}
          bottomRef={bottomRef}
          onScroll={handleScroll}
          fullscreen={fullscreen}
          navbarHeight={navbarHeight}
          loadingMore={loadingMore}
          hasMore={hasMore}
          chatMessages={chatMessages}
          connected={connected}
          agentName={name}
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
