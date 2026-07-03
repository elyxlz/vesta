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

interface ChatProps {
  onCollapse?: () => void;
  fullscreen?: boolean;
}

export function Chat({ onCollapse, fullscreen }: ChatProps = {}) {
  const { name, agent } = useSelectedAgent();
  const notAuthenticated =
    agent?.status === "not_authenticated" || agent?.status === "unprovisioned";
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
    liveThinking,
    liveReply,
    isTyping,
    connected,
    historyLoaded,
    hasMore,
    loadingMore,
    loadMore,
    send,
    showToolCalls,
  } = useAgentSocket();

  const [input, setInput] = useState("");

  useEffect(() => {
    registerChatCallbacks(send, setInput);
  }, [registerChatCallbacks, send]);

  const scrollRef = useRef<ChatScrollHandle>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useChatKeyboardFocus(textareaRef);

  const chatMessages = useMemo(
    () =>
      messages.filter(
        (m) =>
          m.type === "user" ||
          m.type === "chat" ||
          (showToolCalls &&
            m.type === "tool_start" &&
            !(m.tool === "Bash" && m.input.includes("app-chat"))),
      ),
    [messages, showToolCalls],
  );

  const scrollToBottom = useCallback(() => {
    scrollRef.current?.scrollToBottom();
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
    ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`;
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Card
        className={cn(
          "flex flex-col h-full gap-0 py-0 px-0 overflow-hidden relative text-base shadow-none",
          fullscreen && "ring-0",
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
          scrollRef={scrollRef}
          loadMore={loadMore}
          fullscreen={fullscreen}
          navbarHeight={navbarHeight}
          loadingMore={loadingMore}
          hasMore={hasMore}
          chatMessages={chatMessages}
          liveThinking={liveThinking}
          liveReply={liveReply}
          connected={connected}
          historyLoaded={historyLoaded}
          agentName={name}
          notAuthenticated={notAuthenticated}
          isTyping={isTyping}
          isMobile={isMobile}
        />

        <div className="relative">
          <BottomBanner error={voiceError} />
          <ChatComposer
            fullscreen={fullscreen}
            connected={connected}
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
      </Card>
    </div>
  );
}
