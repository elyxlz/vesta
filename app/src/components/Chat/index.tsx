import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Maximize2, Mic, PanelRightClose, SendHorizontal, Square } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { ButtonGroup } from "@/components/ui/button-group";
import { useChat } from "@/hooks/use-chat";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { useVoiceInput } from "@/hooks/use-voice-input";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useLayout } from "@/stores/use-layout";
import { linkify } from "@/lib/linkify";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatProps {
  onCollapse?: () => void;
  fullscreen?: boolean;
}

const thinkingIndicatorVariants = {
  hidden: { height: 0, opacity: 0 },
  visible: {
    height: "auto",
    opacity: 1,
    transition: {
      height: {
        type: "spring" as const,
        stiffness: 420,
        damping: 28,
        mass: 0.65,
      },
      opacity: {
        duration: 0.18,
        ease: [0.2, 0.8, 0.2, 1] as const,
      },
    },
  },
  exit: {
    height: 0,
    opacity: 0,
    transition: {
      height: {
        duration: 0.22,
        ease: [0.32, 0.72, 0, 1] as const,
      },
      opacity: { duration: 0.14, ease: "easeIn" as const },
    },
  },
};

export function Chat({ onCollapse, fullscreen }: ChatProps = {}) {
  const { name, setAgentState, sttStatus, ttsStatus } = useSelectedAgent();
  const navigate = useNavigate();
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const speechEnabled = (ttsStatus?.configured && ttsStatus?.enabled) ?? false;
  const voiceAutoSend = sttStatus?.auto_send ?? true;
  const sttAvailable = (sttStatus?.configured && sttStatus?.enabled) ?? false;
  const { messages, agentState, connected, hasMore, loadingMore, loadMore, send, stopSpeech } = useChat(name, true, speechEnabled);

  useEffect(() => {
    setAgentState(agentState);
  }, [agentState, setAgentState]);

  const [input, setInput] = useState("");
  const voiceDraft = useCallback((text: string) => { setInput(text); }, []);
  const { isRecording, liveTranscript, toggle: toggleVoice, error: voiceError } = useVoiceInput({ agentName: name || "", onSend: send, onDraft: voiceDraft, onRecordingStart: stopSpeech, sttAvailable, voiceAutoSend });
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

  const chatMessages = useMemo(() => messages.filter(
    (m) => m.type === "user" || m.type === "chat" || m.type === "error",
  ), [messages]);

  const isThinking =
    agentState === "thinking" || agentState === "tool_use";

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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  };

  return (
    <Card className={cn(
      "flex flex-col h-full gap-0 py-0 overflow-hidden relative",
      fullscreen && "border-0 rounded-none shadow-none bg-background",
    )}>

      {!fullscreen && (
        <div className="absolute top-2 right-2 z-10 flex flex-col items-end gap-1">
          <ButtonGroup>
            <Button
              size="icon-sm"
              variant="outline"
              className="text-muted-foreground dark:bg-card"
              onClick={() => navigate(`/agent/${name}/chat`)}
            >
              <Maximize2 />
            </Button>
            {onCollapse && (
              <Button
                size="icon-sm"
                variant="outline"
                className="text-muted-foreground dark:bg-card"
                onClick={onCollapse}
              >
                <PanelRightClose />
              </Button>
            )}
          </ButtonGroup>
        </div>
      )}

      <CardContent className="flex-1 min-h-0 overflow-hidden p-0 relative">
        <AnimatePresence>
          {hasNewMessage && (
            <motion.button
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              transition={{ duration: 0.18 }}
              onClick={() => scrollToBottom(scrollRef.current)}
              className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10 rounded-lg border border-primary/20 bg-primary/5 px-3 py-1.5 text-xs text-primary cursor-pointer hover:bg-primary/10 transition-colors"
            >
              new message
            </motion.button>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {loadingMore && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.18 }}
              className="absolute left-1/2 -translate-x-1/2 z-10 pointer-events-none"
              style={{ top: navbarHeight + 32 }}
            >
              <span className="rounded-lg border border-muted-foreground/20 bg-muted/80 backdrop-blur-sm px-3 py-1.5 text-xs text-muted-foreground">
                loading...
              </span>
            </motion.div>
          )}
        </AnimatePresence>
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full min-h-0 overflow-y-auto px-3 pt-6 pb-4"
          style={{ maskImage: "linear-gradient(to bottom, transparent, black 40px, black calc(100% - 24px), transparent)" }}
        >
          <div className={cn("min-h-full flex flex-col", fullscreen && "pt-16 md:pt-20")}>
            <div className="flex-1" />
            <div>
              {!hasMore && chatMessages.length > 0 && (
                <div className="flex justify-center py-3">
                  <span className="text-[11px] text-muted-foreground/40">beginning of conversation</span>
                </div>
              )}
              {chatMessages.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-2">
                  <span className="text-xs text-muted-foreground">
                    {connected
                      ? `${name} is setting things up`
                      : "connecting..."}
                  </span>
                </div>
              ) : (
                <div className="flex flex-col">
                  {chatMessages.map((msg, i) => {
                    const prev = chatMessages[i - 1];
                    const sameGroup = prev && prev.type === msg.type;
                    return (
                      <ChatBubble key={i} event={msg} className={i === 0 ? "" : sameGroup ? "mt-1.5" : "mt-5"} />
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </CardContent>

      <div className="shrink-0 flex flex-col gap-0 px-2 pt-0 pb-3">
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
              onChange={handleInput}
              onKeyDown={handleKeyDown}
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
              onClick={handleSend}
            >
              <SendHorizontal className="text-muted-foreground" />
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

function ChatBubble({ event, className }: { event: VestaEvent; className?: string }) {
  if (event.type === "history" || event.type === "status") return null;

  const ts = event.ts
    ? new Date(event.ts).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
    : "";

  if (event.type === "error") {
    return (
      <div className={cn("flex justify-center px-4 py-1", className)}>
        <span className="text-xs text-destructive">{event.text}</span>
      </div>
    );
  }

  if (event.type !== "user" && event.type !== "chat") return null;

  const isUser = event.type === "user";
  const text = event.text;

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start", className)}>
      <div
        className={cn(
          "flex items-end max-w-[85%] rounded-2xl px-3 py-1.5 text-sm leading-relaxed",
          isUser
            ? "bg-primary text-primary-foreground rounded-br-sm"
            : "bg-muted text-foreground rounded-bl-sm",
        )}
      >
        <span className="min-w-0 break-words" dangerouslySetInnerHTML={{ __html: linkify(text) }} />
        {ts && (
          <span
            className={cn(
              "shrink-0 ml-auto pl-2 text-[10px] leading-relaxed select-none whitespace-nowrap",
              isUser ? "text-primary-foreground/50" : "text-muted-foreground/50",
            )}
          >
            {ts}
          </span>
        )}
      </div>
    </div>
  );
}

function ThinkingDots({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2 py-1", className)}>
      <span className="text-xs text-muted-foreground">Thinking</span>
      <div className="flex items-center gap-1">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="size-[5px] rounded-full bg-primary"
            animate={{ opacity: [0.25, 1, 0.25] }}
            transition={{
              duration: 1.5,
              repeat: Infinity,
              ease: "easeInOut",
              delay: i * 0.3,
            }}
          />
        ))}
      </div>
    </div>
  );
}
