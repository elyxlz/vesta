import { useEffect, useRef, useState } from "react";
import { streamGatewayLogs, stopGatewayLogs } from "@/api/gateway";
import { LOG_SCROLLBACK_LINES } from "@/lib/log-stream-policy";
import { LogScroller, StreamingIndicator } from "@/components/LogScroller";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { BOTTOM_FADE_PX } from "@/hooks/use-scroll-fade";
import type { LogEvent } from "@/lib/types";
import { LogLevelColors } from "./styles";

// The floating header sits over the terminal like the fullscreen console's navbar. The
// first line clears the header by HEADER_H, and the top fade dissolves the tail over
// twice that, matching the native dialog mask (dialogScrollMask); the bottom softens by
// the shared BOTTOM_FADE_PX.
const HEADER_H = 68;

// vestad writes plain-text logs as `<timestamp>  <LEVEL>  <message>`. Split that
// shape so the viewer can dim the timestamp and color the level; anything that
// doesn't match (continuations, "error:" lines) renders as-is.
const LOG_LINE_RE = /^(\S+)\s+(TRACE|DEBUG|INFO|WARN|ERROR)\s+([\s\S]*)$/;

const LINE_CLASS = "px-3.5 break-words whitespace-pre-wrap";

function LogLine({ text }: { text: string }) {
  const match = LOG_LINE_RE.exec(text);
  const [, timestamp, level, rest] = match ?? [];
  if (timestamp === undefined || level === undefined || rest === undefined) {
    return <div className={LINE_CLASS}>{text || " "}</div>;
  }
  return (
    <div className={LINE_CLASS}>
      <span className="text-white/40">{timestamp}</span>{" "}
      <span style={{ color: LogLevelColors[level], fontWeight: 600 }}>
        {level}
      </span>{" "}
      {rest}
    </div>
  );
}

interface GatewayLogsViewerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface GatewayLogLine {
  id: number;
  text: string;
}

export function GatewayLogsViewer({
  open,
  onOpenChange,
}: GatewayLogsViewerProps) {
  const [lines, setLines] = useState<GatewayLogLine[]>([]);
  const nextIdRef = useRef(0);

  useEffect(() => {
    if (!open) return;
    setLines([]);
    nextIdRef.current = 0;
    let active = true;

    const append = (text: string) =>
      setLines((prev) => {
        const next = [...prev, { id: nextIdRef.current++, text }];
        return next.length > LOG_SCROLLBACK_LINES
          ? next.slice(-LOG_SCROLLBACK_LINES)
          : next;
      });

    const handleEvent = (event: LogEvent) => {
      if (!active) return;
      switch (event.kind) {
        case "Line":
          append(event.text);
          break;
        case "Error":
          append(event.message);
          break;
        case "End":
          break;
      }
    };

    // Follows the tail live; every failure arrives as an Error event instead.
    void streamGatewayLogs(true, handleEvent);

    return () => {
      active = false;
      stopGatewayLogs();
    };
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        bare
        className="h-[70vh] w-[70vw] max-w-[900px] sm:max-w-[900px]"
      >
        <div className="relative h-full">
          <LogScroller
            lines={lines}
            fade={{ top: HEADER_H * 2, bottom: BOTTOM_FADE_PX }}
            placeholder={<StreamingIndicator />}
            topSpacer={<div style={{ height: HEADER_H }} />}
            footer={<div className="h-4" />}
            renderLine={(line) => <LogLine key={line.id} text={line.text} />}
          />

          {/* The native dialog header, floated over the terminal (like the fullscreen
              console's navbar); the fade behind it lets the log tail dissolve up under it. */}
          <div className="pointer-events-none absolute inset-x-0 top-0 z-10 bg-gradient-to-b from-[#1a1a1a] via-[#1a1a1a]/85 to-transparent">
            <DialogHeader>
              <DialogTitle className="text-white/90">Gateway logs</DialogTitle>
              <DialogDescription className="sr-only">
                Recent vestad gateway logs
              </DialogDescription>
            </DialogHeader>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
