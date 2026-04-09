import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { useLayout } from "@/stores/use-layout";
import { streamLogs, stopLogs } from "@/api";
import { stripAnsi } from "@/lib/ansi";
import { linkify } from "@/lib/linkify";
import { cn } from "@/lib/utils";

const MAX_LINES = 5000;
const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;

const LOG_LEVEL_TAGS = new Set(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]);
const FAMILY_TAGS = new Set(["AGENT", "SYSTEM", "USER", "EVENT"]);

const FAMILY_COLOR_CLASS: Record<string, string> = {
  AGENT: "text-fuchsia-300/90",
  SYSTEM: "text-green-300/90",
  USER: "text-white/90",
  EVENT: "text-yellow-300/90",
};

const SUBFAMILY_COLOR_CLASS: Record<string, Record<string, string>> = {
  AGENT: {
    ASSISTANT: "text-fuchsia-200/90",
    THINKING: "text-fuchsia-300/90",
    "TOOL CALL": "text-fuchsia-400/90",
    SUBAGENT: "text-fuchsia-500/90",
  },
  SYSTEM: {
    INIT: "text-green-200/90",
    STARTUP: "text-green-300/90",
    SHUTDOWN: "text-green-500/90",
    CLIENT: "text-green-400/90",
    DREAMER: "text-green-200/90",
    INTERRUPT: "text-green-500/90",
    PROACTIVE: "text-green-200/90",
    MESSAGE: "text-green-300/90",
    SDK: "text-green-500/90",
    USAGE: "text-green-400/90",
  },
  USER: {
    MESSAGE: "text-white/90",
  },
  EVENT: {
    NOTIFICATION: "text-yellow-200/90",
  },
};

const LEGACY_TAG_TO_FAMILY: Record<string, string> = {
  ASSISTANT: "AGENT",
  THINKING: "AGENT",
  "TOOL CALL": "AGENT",
  TOOL: "AGENT",
  SUBAGENT: "AGENT",
  INIT: "SYSTEM",
  STARTUP: "SYSTEM",
  SHUTDOWN: "SYSTEM",
  CLIENT: "SYSTEM",
  DREAMER: "SYSTEM",
  INTERRUPT: "SYSTEM",
  PROACTIVE: "SYSTEM",
  SDK: "SYSTEM",
  USAGE: "SYSTEM",
  USER: "USER",
  NOTIFICATION: "EVENT",
};

function extractTags(line: string): string[] {
  return [...line.matchAll(/\[([A-Z ]+)\]/g)]
    .map((match) => match[1])
    .filter((tag) => !LOG_LEVEL_TAGS.has(tag));
}

function lineColorClass(line: string): string | null {
  const tags = extractTags(line);
  const familyIndex = tags.findIndex((tag) => FAMILY_TAGS.has(tag));

  if (familyIndex !== -1) {
    const family = tags[familyIndex];
    const subfamily = tags[familyIndex + 1];
    return (subfamily && SUBFAMILY_COLOR_CLASS[family]?.[subfamily]) || FAMILY_COLOR_CLASS[family] || null;
  }

  const legacyTag = tags.find((tag) => tag in LEGACY_TAG_TO_FAMILY);
  if (!legacyTag) return null;

  const family = LEGACY_TAG_TO_FAMILY[legacyTag];
  return SUBFAMILY_COLOR_CLASS[family]?.[legacyTag] || FAMILY_COLOR_CLASS[family] || null;
}

interface ConsoleProps {
  name: string;
  onClose?: () => void;
  fullscreen?: boolean;
}

export function Console({ name, onClose, fullscreen }: ConsoleProps) {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const [lines, setLines] = useState<string[]>([]);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { check, scroll } = useAutoScroll();
  const reconnectDelayRef = useRef(RECONNECT_BASE);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef(true);

  const startStreamRef = useRef<() => void>(undefined);
  startStreamRef.current = () => {
    if (!name || !activeRef.current) return;
    stopLogs(name);
    setEnded(false);

    streamLogs(name, (event) => {
      switch (event.kind) {
        case "Line": {
          const stripped = stripAnsi(event.text);
          setLines((prev) => {
            const next = [...prev, stripped];
            return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
          });
          break;
        }
        case "End":
        case "Error":
          setEnded(true);
          if (activeRef.current) {
            reconnectTimerRef.current = setTimeout(() => {
              reconnectDelayRef.current = Math.min(
                reconnectDelayRef.current * 2,
                RECONNECT_MAX,
              );
              startStreamRef.current?.();
            }, reconnectDelayRef.current);
          }
          break;
      }
    }).then(() => {
      reconnectDelayRef.current = RECONNECT_BASE;
    });
  };

  useEffect(() => {
    activeRef.current = true;
    setLines([]);
    startStreamRef.current?.();
    return () => {
      activeRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (name) stopLogs(name);
    };
  }, [name]);

  useLayoutEffect(() => {
    scroll(scrollRef.current);
  }, [lines, scroll]);

  const handleScroll = () => {
    check(scrollRef.current);
  };

  useEffect(() => {
    if (!onClose) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  return (
    <div className={cn(
      "flex flex-col h-full",
      fullscreen && "dark dark-overlay bg-[#1a1a1a] text-[#e8e8e8]",
    )}>
      {!fullscreen && (
        <div className="flex items-center justify-between px-4 py-3 min-h-11 shrink-0 border-b border-white/5">
          <span className="text-sm font-medium">{name} logs</span>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="size-9"
                onClick={onClose}
              >
                <X className="size-5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>close</TooltipContent>
          </Tooltip>
        </div>
      )}

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className={cn(
          "flex-1 overflow-y-auto font-mono text-xs leading-[1.6] text-white/70",
          fullscreen ? "px-page pb-page" : "px-3 py-2",
        )}
        style={fullscreen ? {
          paddingTop: `calc(${navbarHeight}px + var(--page-padding-x))`,
          maskImage: `linear-gradient(to bottom, transparent, black ${navbarHeight * 2}px, black calc(100% - 20px), transparent)`,
        } : undefined}
      >
        <div className="min-h-full flex flex-col justify-end">
          <div>
            {lines.length === 0 && !ended && (
              <div className="flex flex-col items-center gap-2 py-1">
                <div className="flex items-center gap-1">
                  <div className="size-[5px] rounded-full bg-white/30 opacity-60" />
                  <div className="size-[5px] rounded-full bg-white/30 opacity-40" />
                  <div className="size-[5px] rounded-full bg-white/30 opacity-20" />
                </div>
                <span className="text-xs text-[#666]">streaming logs...</span>
              </div>
            )}

            {lines.map((line, i) => (
              <div
                key={i}
                className={cn(
                  "break-words whitespace-pre-wrap",
                  lineColorClass(line),
                )}
                dangerouslySetInnerHTML={{ __html: linkify(line) }}
              />
            ))}

            {ended && (
              <div className="text-center text-[#444] py-2">
                — reconnecting —
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
