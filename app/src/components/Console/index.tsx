import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { streamLogs, stopLogs } from "@/api";
import { stripAnsi } from "@/lib/ansi";
import { linkify } from "@/lib/linkify";

const MAX_LINES = 5000;
const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;

interface ConsoleProps {
  name: string;
  onClose: () => void;
}

export function Console({ name, onClose }: ConsoleProps) {

  const [lines, setLines] = useState<string[]>([]);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { check, scroll } = useAutoScroll();
  const reconnectDelayRef = useRef(RECONNECT_BASE);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef(true);

  const startStream = () => {
    if (!name || !activeRef.current) return;
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
          setEnded(true);
          if (activeRef.current) {
            reconnectTimerRef.current = setTimeout(() => {
              reconnectDelayRef.current = Math.min(
                reconnectDelayRef.current * 2,
                RECONNECT_MAX,
              );
              startStream();
            }, reconnectDelayRef.current);
          }
          break;
        case "Error":
          setEnded(true);
          if (activeRef.current) {
            reconnectTimerRef.current = setTimeout(() => {
              reconnectDelayRef.current = Math.min(
                reconnectDelayRef.current * 2,
                RECONNECT_MAX,
              );
              startStream();
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
    startStream();
    return () => {
      activeRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (name) stopLogs(name);
    };
  }, [name, startStream]);

  useLayoutEffect(() => {
    scroll(scrollRef.current);
  }, [lines, scroll]);

  const handleScroll = () => {
    check(scrollRef.current);
  };

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [onClose]);

  return (
    <div className="flex flex-col h-full">
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

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-3 py-2 font-mono text-xs leading-[1.6] text-white/70"
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
                className="break-all"
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
