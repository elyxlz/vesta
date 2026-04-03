import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { Maximize2, PanelRightClose, SendHorizontal } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
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
}

export function Chat({ onCollapse, fullscreen }: ChatProps = {}) {
  const { name, setAgentState } = useSelectedAgent();
  const navigate = useNavigate();
  const { messages, agentState, connected, send } = useAgentWs(name, true);

  useEffect(() => {
    setAgentState(agentState);
  }, [agentState, setAgentState]);

  const [input, setInput] = useState("");
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
    (m) =>
      m.type !== "tool_start" &&
      m.type !== "tool_end" &&
      m.type !== "notification",
  );

  useLayoutEffect(() => {
    scroll(scrollRef.current);
  }, [filteredMessages, scroll]);

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

  const isThinking =
    agentState === "thinking" || agentState === "tool_use";

  return (
    <Card className={cn(
      "flex flex-col h-full gap-0 py-0 overflow-hidden relative",
      fullscreen && "border-0 rounded-none shadow-none bg-background",
    )}>

      {!fullscreen && (
        <ButtonGroup className="absolute top-2 right-2 z-10">
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
          <Button
            size="icon-sm"
            variant="outline"
            className="text-muted-foreground dark:bg-card"
            onClick={() => navigate(`/agent/${name}/chat`)}
          >
            <Maximize2 />
          </Button>
        </ButtonGroup>
      )}

      <AnimatePresence>
        {showReconnect && (
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

      <CardContent
        className="flex-1 overflow-y-auto p-0 min-h-0"
        style={{ maskImage: "linear-gradient(to bottom, transparent, black 80px, black calc(100% - 24px), transparent)" }}
      >
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full overflow-y-auto px-4 py-3 font-mono text-sm leading-relaxed"
        >
          <div className={cn("min-h-full flex flex-col justify-end", fullscreen && "pt-16")}>
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
                <>
                  {filteredMessages.map((msg, i) => (
                    <MessageLine key={i} event={msg} />
                  ))}
                  <AnimatePresence>
                    {isThinking && filteredMessages.length > 0 && (
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.15 }}
                      >
                        <ThinkingDots />
                      </motion.div>
                    )}
                  </AnimatePresence>
                </>
              )}
            </div>
          </div>
        </div>
      </CardContent>

      <CardFooter className="border-t shrink-0 p-3 px-4 !pt-3">
        <div className="flex items-end gap-2.5 w-full">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={connected ? "send a message..." : "connecting..."}
            disabled={!connected}
            rows={1}
            className="m-0 flex-1 min-h-9 max-h-[120px] bg-transparent py-2.5 text-sm font-mono leading-5 resize-none outline-none placeholder:text-muted-foreground/50 disabled:opacity-50"
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
      </CardFooter>
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
      colorClass = "text-muted-foreground text-xs";
      content = `[${event.tool}] ${event.input}`;
      break;
    case "tool_end":
      colorClass = "text-muted-foreground text-xs";
      content = `[${event.tool}] done`;
      break;
    case "notification":
      colorClass = "text-amber-600 dark:text-amber-400 text-xs";
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
        className="break-words min-w-0"
        dangerouslySetInnerHTML={{ __html: linkify(content) }}
      />
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      <div className="size-[5px] rounded-full bg-primary/60 opacity-60" />
      <div className="size-[5px] rounded-full bg-primary/60 opacity-40" />
      <div className="size-[5px] rounded-full bg-primary/60 opacity-20" />
    </div>
  );
}
