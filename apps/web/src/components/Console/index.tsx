import { forwardRef, useEffect, useMemo, useRef, useState } from "react";
import { Virtuoso, type Components } from "react-virtuoso";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useLayout } from "@/stores/use-layout";
import { streamLogs, stopLogs } from "@/api";
import { stripAnsi } from "@/lib/ansi";
import { linkify } from "@/lib/linkify";
import { cn } from "@/lib/utils";

const MAX_LINES = 5000;
const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;
const START_INDEX = 1_000_000;

const LOG_LEVEL_TAGS = new Set([
  "DEBUG",
  "INFO",
  "WARNING",
  "ERROR",
  "CRITICAL",
]);
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
    return (
      (subfamily && SUBFAMILY_COLOR_CLASS[family]?.[subfamily]) ||
      FAMILY_COLOR_CLASS[family] ||
      null
    );
  }

  return null;
}

interface LogLine {
  id: number;
  colorClass: string | null;
  html: string;
}

interface ConsoleContext {
  fullscreen?: boolean;
  navbarHeight: number;
  ended: boolean;
}

const Scroller: Components<LogLine, ConsoleContext>["Scroller"] = forwardRef(
  function Scroller({ context, style, ...props }, ref) {
    const fullscreen = context?.fullscreen;
    const navbarHeight = context?.navbarHeight ?? 0;
    return (
      <div
        {...props}
        ref={ref}
        className={fullscreen ? "px-page pb-page" : "px-3 py-2"}
        style={{
          ...style,
          ...(fullscreen
            ? {
                paddingTop: `calc(${navbarHeight}px + var(--page-padding-x))`,
                maskImage: `linear-gradient(to bottom, transparent, black ${navbarHeight * 2}px, black calc(100% - 15px), transparent)`,
              }
            : {}),
        }}
      />
    );
  },
);

function ReconnectingNotice() {
  return <div className="text-center text-[#444] py-2">— reconnecting —</div>;
}

function Footer({ context }: { context?: ConsoleContext }) {
  if (!context?.ended) return null;
  return <ReconnectingNotice />;
}

function EmptyPlaceholder({ context }: { context?: ConsoleContext }) {
  if (context?.ended) return <ReconnectingNotice />;
  return (
    <div className="min-h-full flex flex-col items-center justify-end gap-2 py-1">
      <div className="flex items-center gap-1">
        <div className="size-[5px] rounded-full bg-white/30 opacity-60" />
        <div className="size-[5px] rounded-full bg-white/30 opacity-40" />
        <div className="size-[5px] rounded-full bg-white/30 opacity-20" />
      </div>
      <span className="text-xs text-[#666]">streaming logs...</span>
    </div>
  );
}

const consoleComponents: Components<LogLine, ConsoleContext> = {
  Scroller,
  Footer,
  EmptyPlaceholder,
};

interface ConsoleProps {
  name: string;
  onClose?: () => void;
  fullscreen?: boolean;
}

export function Console({ name, onClose, fullscreen }: ConsoleProps) {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [ended, setEnded] = useState(false);
  const idRef = useRef(0);
  const reconnectDelayRef = useRef(RECONNECT_BASE);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef(true);

  const startStream = useRef<() => void>(undefined);

  useEffect(() => {
    startStream.current = () => {
      if (!name || !activeRef.current) return;
      stopLogs(name);
      setEnded(false);

      streamLogs(name, (event) => {
        switch (event.kind) {
          case "Line": {
            // A line means the connection is healthy, so reset the backoff.
            reconnectDelayRef.current = RECONNECT_BASE;
            const stripped = stripAnsi(event.text);
            setLines((prev) => {
              const next = [
                ...prev,
                {
                  id: idRef.current++,
                  colorClass: lineColorClass(stripped),
                  html: linkify(stripped),
                },
              ];
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
                startStream.current?.();
              }, reconnectDelayRef.current);
            }
            break;
        }
      });
    };
  });

  useEffect(() => {
    activeRef.current = true;
    idRef.current = 0;
    setLines([]);
    startStream.current?.();
    return () => {
      activeRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (name) stopLogs(name);
    };
  }, [name]);

  useEffect(() => {
    if (!onClose) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  const context = useMemo<ConsoleContext>(
    () => ({ fullscreen, navbarHeight, ended }),
    [fullscreen, navbarHeight, ended],
  );
  const firstItemIndex =
    lines.length > 0 ? START_INDEX + lines[0].id : START_INDEX;

  return (
    <div
      className={cn(
        "flex flex-col h-full",
        fullscreen && "dark dark-overlay bg-[#1a1a1a] text-[#e8e8e8]",
      )}
    >
      {!fullscreen && (
        <div className="flex items-center justify-between px-4 py-3 min-h-11 shrink-0 border-b border-white/5">
          <span className="text-sm font-medium">{name} logs</span>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="size-9"
                aria-label="close logs"
                onClick={onClose}
              >
                <X className="size-5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>close</TooltipContent>
          </Tooltip>
        </div>
      )}

      <div className="flex-1 min-h-0">
        <Virtuoso<LogLine, ConsoleContext>
          className="h-full font-mono text-xs leading-[1.6] text-white/70"
          data={lines}
          context={context}
          components={consoleComponents}
          firstItemIndex={firstItemIndex}
          computeItemKey={(_index, line) => line.id}
          alignToBottom
          followOutput={(atBottom) => (atBottom ? "auto" : false)}
          atBottomThreshold={80}
          initialTopMostItemIndex={{ index: "LAST", align: "end" }}
          itemContent={(_index, line) => (
            <div
              className={cn("break-words whitespace-pre-wrap", line.colorClass)}
              dangerouslySetInnerHTML={{ __html: line.html }}
            />
          )}
        />
      </div>
    </div>
  );
}
