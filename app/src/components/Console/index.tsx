import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { useNavigation } from "@/stores/use-navigation";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { streamLogs, stopLogs } from "@/api";
import { stripAnsi } from "@/lib/ansi";
import { linkify } from "@/lib/linkify";

const MAX_LINES = 5000;
const RECONNECT_BASE = 1000;
const RECONNECT_MAX = 30000;

export function Console() {
  const selectedAgent = useNavigation((s) => s.selectedAgent);
  const navigateToAgent = useNavigation((s) => s.navigateToAgent);
  const name = selectedAgent ?? "";

  const [lines, setLines] = useState<string[]>([]);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { check, scroll } = useAutoScroll();
  const reconnectDelayRef = useRef(RECONNECT_BASE);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef(true);

  const startStream = useCallback(() => {
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
  }, [name]);

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

  const handleScroll = useCallback(() => {
    check(scrollRef.current);
  }, [check]);

  const handleBack = useCallback(() => {
    navigateToAgent(name);
  }, [navigateToAgent, name]);

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") navigateToAgent(name);
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [navigateToAgent, name]);

  return (
    <div className="dark dark-overlay absolute inset-0 flex flex-col bg-[#1a1a1a] text-[#e8e8e8] z-10 animate-view-in">
      <div className="flex items-center px-3 h-9 shrink-0 border-b border-white/5">
        <button
          onClick={handleBack}
          className="flex items-center gap-1 text-[12px] text-[#888] hover:text-white transition-colors"
        >
          <ArrowLeft size={14} />
          back
        </button>
        <span className="text-[13px] font-medium ml-auto mr-auto">{name}</span>
        <div className="w-[40px]" />
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-3 py-2 font-mono text-[11px] leading-[1.6] text-white/70"
      >
        {lines.length === 0 && !ended && (
          <div className="flex flex-col items-center justify-center h-full gap-2">
            <div className="flex items-center gap-1">
              <div className="w-[5px] h-[5px] rounded-full bg-white/30 animate-dot-pulse-1" />
              <div className="w-[5px] h-[5px] rounded-full bg-white/30 animate-dot-pulse-2" />
              <div className="w-[5px] h-[5px] rounded-full bg-white/30 animate-dot-pulse-3" />
            </div>
            <span className="text-[11px] text-[#666]">streaming logs...</span>
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
  );
}
