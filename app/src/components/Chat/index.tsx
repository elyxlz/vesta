import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ArrowLeft, Wrench } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useNavigation } from "@/stores/use-navigation";
import { useAgentWs } from "@/hooks/use-agent-ws";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { linkify } from "@/lib/linkify";
import type { VestaEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

export function Chat() {
  const selectedAgent = useNavigation((s) => s.selectedAgent);
  const navigateToAgent = useNavigation((s) => s.navigateToAgent);
  const name = selectedAgent ?? "";

  const { messages, agentState, connected, send } = useAgentWs(name, true);

  const [showTools, setShowTools] = useState(false);
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

  const filteredMessages = useMemo(
    () =>
      showTools
        ? messages
        : messages.filter(
            (m) =>
              m.type !== "tool_start" &&
              m.type !== "tool_end" &&
              m.type !== "notification",
          ),
    [messages, showTools],
  );

  useLayoutEffect(() => {
    scroll(scrollRef.current);
  }, [filteredMessages, scroll]);

  const handleScroll = useCallback(() => {
    check(scrollRef.current);
  }, [check]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text) return;
    if (send(text)) {
      setInput("");
      const ta = textareaRef.current;
      if (ta) ta.style.height = "auto";
    }
  }, [input, send]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
      if (e.key === "Escape") {
        if (!input && document.activeElement !== textareaRef.current) {
          navigateToAgent(name);
        } else if (!input) {
          navigateToAgent(name);
        }
      }
    },
    [handleSend, input, navigateToAgent, name],
  );

  useEffect(() => {
    const handleGlobalEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !input) {
        navigateToAgent(name);
      }
    };
    window.addEventListener("keydown", handleGlobalEsc);
    return () => window.removeEventListener("keydown", handleGlobalEsc);
  }, [input, navigateToAgent, name]);

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  }, []);

  const handleBack = useCallback(() => {
    navigateToAgent(name);
  }, [navigateToAgent, name]);

  const isThinking =
    agentState === "thinking" || agentState === "tool_use";

  const statusDot = connected
    ? isThinking
      ? "bg-amber-400"
      : "bg-primary"
    : "bg-muted-foreground/50";
  const statusTip = connected
    ? isThinking
      ? agentState === "tool_use"
        ? "using a tool"
        : "thinking"
      : "connected"
    : "disconnected";

  return (
    <div className="dark dark-overlay absolute inset-0 flex flex-col bg-[#1a1a1a] text-[#e8e8e8] z-10 animate-view-in">
      {/* Top bar */}
      <div className="flex items-center justify-between px-3 h-9 shrink-0 border-b border-white/5">
        <button
          onClick={handleBack}
          className="flex items-center gap-1 text-sm text-[#888] hover:text-white transition-colors"
        >
          <ArrowLeft size={14} />
          back
        </button>
        <span className="text-sm font-medium">{name}</span>
        <div className="flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger>
              <div className={cn("w-[6px] h-[6px] rounded-full", statusDot)} />
            </TooltipTrigger>
            <TooltipContent>{statusTip}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => setShowTools(!showTools)}
                className={cn(
                  "p-1 rounded transition-colors",
                  showTools
                    ? "text-white bg-white/10"
                    : "text-[#666] hover:text-white",
                )}
              >
                <Wrench size={13} />
              </button>
            </TooltipTrigger>
            <TooltipContent>
              {showTools ? "hide tools" : "show tools"}
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      {showReconnect && (
        <div className="text-center py-1 bg-amber-500/20 text-amber-300 text-xs">
          reconnecting...
        </div>
      )}

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-3 py-2 font-mono text-sm leading-[1.6]"
      >
        {filteredMessages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-2">
            <ThinkingDots />
            <span className="text-xs text-[#666]">
              {connected
                ? `${name} is listening. say something.`
                : "connecting..."}
            </span>
          </div>
        )}

        {filteredMessages.map((msg, i) => (
          <MessageLine key={i} event={msg} />
        ))}

        {isThinking && filteredMessages.length > 0 && <ThinkingDots />}
      </div>

      {/* Input */}
      <div className="flex items-end gap-2 px-3 py-2 border-t border-white/5">
        <span className="text-sm font-mono text-[#666] leading-[1.6] shrink-0 pb-[2px]">
          &gt;
        </span>
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={connected ? "send a message..." : "connecting..."}
          disabled={!connected}
          rows={1}
          className="flex-1 bg-transparent text-sm font-mono leading-[1.6] resize-none outline-none placeholder:text-[#444] disabled:opacity-50"
        />
      </div>
    </div>
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

  let className = "text-[rgba(140,200,130,0.9)]";
  let content = "";

  switch (event.type) {
    case "user":
      className = "text-white";
      content = `> ${event.text}`;
      break;
    case "assistant":
      className = "text-[rgba(140,200,130,0.9)]";
      content = event.text;
      break;
    case "tool_start":
      className = "text-white/40 text-xs";
      content = `[${event.tool}] ${event.input}`;
      break;
    case "tool_end":
      className = "text-white/40 text-xs";
      content = `[${event.tool}] done`;
      break;
    case "notification":
      className = "text-[rgba(200,170,100,0.8)] text-xs";
      content = `[${event.source}] ${event.summary}`;
      break;
    case "error":
      className = "text-[rgba(224,112,112,0.9)]";
      content = `error: ${event.text}`;
      break;
    case "status":
      return null;
    default:
      return null;
  }

  return (
    <div className={cn("flex gap-2 py-[1px]", className)}>
      {ts && (
        <span className="text-xs text-white/20 shrink-0 leading-[1.9] select-none">
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
      <div className="w-[5px] h-[5px] rounded-full bg-[rgba(140,200,130,0.6)] animate-dot-pulse-1" />
      <div className="w-[5px] h-[5px] rounded-full bg-[rgba(140,200,130,0.6)] animate-dot-pulse-2" />
      <div className="w-[5px] h-[5px] rounded-full bg-[rgba(140,200,130,0.6)] animate-dot-pulse-3" />
    </div>
  );
}
