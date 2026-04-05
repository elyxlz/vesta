import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { Maximize2, PanelRightClose, SendHorizontal, Wrench } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { ButtonGroup } from "@/components/ui/button-group";
import { useAgentWs } from "@/hooks/use-agent-ws";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { linkify } from "@/lib/linkify";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatProps {
  onCollapse?: () => void;
  fullscreen?: boolean;
  showToolCalls?: boolean;
  onToggleToolCalls?: () => void;
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

export function Chat({ onCollapse, fullscreen, showToolCalls: controlledShowToolCalls, onToggleToolCalls }: ChatProps = {}) {
  const { name, setAgentState } = useSelectedAgent();
  const navigate = useNavigate();
  const { messages, agentState, connected, send } = useAgentWs(name, true);

  useEffect(() => {
    setAgentState(agentState);
  }, [agentState, setAgentState]);

  const [input, setInput] = useState("");
  const [internalShowToolCalls, setInternalShowToolCalls] = useState(false);
  const showToolCalls = controlledShowToolCalls ?? internalShowToolCalls;
  const toggleToolCalls = onToggleToolCalls ?? (() => setInternalShowToolCalls((v) => !v));
  const [wasConnected, setWasConnected] = useState(false);
  const [showReconnect, setShowReconnect] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { check, scroll } = useAutoScroll();

  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (connected) {
      setWasConnected(true);
      setShowReconnect(false);
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    } else if (wasConnected) {
      reconnectTimerRef.current = setTimeout(() => {
        setShowReconnect(true);
      }, 2000);
    }
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    };
  }, [connected, wasConnected]);

  const filteredMessages = messages.filter(
    (m) => {
      if (m.type === "notification") return false;
      if ((m.type === "tool_start" || m.type === "tool_end") && !showToolCalls) return false;
      return true;
    },
  );

  const isThinking =
    agentState === "thinking" || agentState === "tool_use";

  const showThinkingIndicator =
    isThinking && filteredMessages.length > 0;

  useLayoutEffect(() => {
    scroll(scrollRef.current);
  }, [filteredMessages, scroll]);

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
  }, [showThinkingIndicator, scroll]);

  const handleScroll = () => {
    check(scrollRef.current);
  };

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
          <Button
            size="icon-sm"
            variant="outline"
            className={cn(
              "dark:bg-card",
              showToolCalls ? "text-primary" : "text-muted-foreground",
            )}
            onClick={toggleToolCalls}
          >
            <Wrench />
          </Button>
        </div>
      )}

      <CardContent className="flex-1 min-h-0 overflow-hidden p-0">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full min-h-0 overflow-y-auto px-4 py-3 font-mono text-sm leading-relaxed"
          style={{ maskImage: "linear-gradient(to bottom, transparent, black 80px, black calc(100% - 24px), transparent)" }}
        >
          <div className={cn("min-h-full flex flex-col justify-end", fullscreen && "pt-12")}>
            <div>
              {filteredMessages.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-2">
                  <ThinkingDots />
                  <span className="text-xs text-muted-foreground">
                    {connected
                      ? `${name} is listening`
                      : "connecting..."}
                  </span>
                </div>
              ) : (
                <div className="flex flex-col gap-0 sm:gap-2">
                  {filteredMessages.map((msg, i) => (
                    <MessageLine key={i} event={msg} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </CardContent>

      <AnimatePresence>
        {showReconnect && !connected && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="text-center py-2 bg-amber-500/10 text-amber-600 dark:text-amber-400 text-xs overflow-hidden shrink-0"
          >
            reconnecting...
          </motion.div>
        )}
      </AnimatePresence>

      <div className="shrink-0 flex flex-col gap-0 px-2 pt-1 pb-3">
        <AnimatePresence>
          {showThinkingIndicator && (
            <motion.div
              variants={thinkingIndicatorVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="shrink-0 overflow-hidden"
            >
              <div className="px-4 pb-2">
                <ThinkingDots className="py-0" />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div className="flex items-center gap-2.5 w-full rounded-xl border bg-card shadow-md px-4 min-h-12">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={connected ? "send a message..." : "connecting..."}
            disabled={!connected}
            rows={1}
            enterKeyHint="send"
            className="m-0 flex-1 min-h-5 max-h-[120px] bg-transparent py-2.5 text-base sm:text-sm font-mono leading-5 resize-none outline-none placeholder:text-muted-foreground/50 disabled:opacity-50"
          />
          <Button
            size="icon-sm"
            variant="ghost"
            className="shrink-0"
            disabled={!connected || !input.trim()}
            onClick={handleSend}
          >
            <SendHorizontal className="text-muted-foreground" />
          </Button>
        </div>
      </div>
    </Card>
  );
}

function MessageLine({ event }: { event: VestaEvent }) {
  if (event.type === "history") return null;

  const ts = event.ts
    ? new Date(event.ts).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
    : "";

  let colorClass = "text-primary";
  let contentClass = "";
  let content = "";

  switch (event.type) {
    case "user":
      colorClass = "text-foreground font-medium";
      content = `> ${event.text}`;
      break;
    case "assistant":
      colorClass = "text-primary/90";
      content = event.text;
      break;
    case "tool_start":
      colorClass = "text-muted-foreground";
      contentClass = "text-xs leading-[1.9]";
      content = `[${event.tool}] ${event.input}`;
      break;
    case "tool_end":
      colorClass = "text-muted-foreground";
      contentClass = "text-xs leading-[1.9]";
      content = `[${event.tool}] done`;
      break;
    case "notification":
      colorClass = "text-amber-600 dark:text-amber-400";
      contentClass = "text-xs leading-[1.9]";
      content = `[${event.source}] ${event.summary}`;
      break;
    case "error":
      colorClass = "text-destructive";
      content = `error: ${event.text}`;
      break;
    case "status":
      return null;
    default:
      return null;
  }

  return (
    <div className={cn("flex gap-2 py-[1px] max-sm:flex-col max-sm:gap-0 max-sm:mt-2", colorClass)}>
      {ts && (
        <span className="text-xs text-muted-foreground/40 shrink-0 leading-[1.9] select-none">
          {ts}
        </span>
      )}
      <span
        className={cn("break-words min-w-0", contentClass)}
        dangerouslySetInnerHTML={{ __html: linkify(content) }}
      />
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
